"""File service for downloading and handling files"""
import asyncio
import os
import re
import shutil
import tempfile
import time
from typing import Any, Callable, Optional, Tuple, Dict, Awaitable, Coroutine

import httpx
import yt_dlp
from yt_dlp.utils import DownloadError
from config.settings import TEMP_DIR, MAX_FILE_SIZE, DOWNLOAD_TIMEOUT, YT_COOKIES_FILE
from utils.logger import setup_logger

logger = setup_logger(__name__)


def _format_size(n: int) -> str:
    """Format bytes to human readable size"""
    from math import log2
    units = ["B", "KB", "MB", "GB", "TB"]
    if n <= 0:
        return "0 B"
    idx = min(int(log2(n) / 10), len(units) - 1)
    return f"{n / (1 << (10 * idx)):.2f} {units[idx]}"


class FileService:
    """Service for file operations"""
    
    def __init__(self):
        self.temp_dir = TEMP_DIR
        self.max_size = MAX_FILE_SIZE
        self.timeout = DOWNLOAD_TIMEOUT
        self.ffmpeg_available = shutil.which("ffmpeg") is not None
        self.cookie_file_path = (
            YT_COOKIES_FILE if YT_COOKIES_FILE and os.path.exists(YT_COOKIES_FILE) else None
        )
        
        # Ensure temp directory exists
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
            logger.info(f"Created temp directory: {self.temp_dir}")
    
    async def download_file(
        self,
        url: str,
        progress_callback: Optional[Callable[[int, Optional[int], float], Coroutine[Any, Any, None]]] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Download file from URL.
        
        Args:
            url: File URL
            progress_callback: Optional async callback invoked periodically with
                (downloaded_bytes, total_bytes or None, speed_bytes_per_sec)
            
        Returns:
            Tuple of (success, message, local_file_path)
        """
        local_file_path = None
        
        try:
            # Special handling for Google Drive shared links
            if "drive.google.com" in url or "docs.googleusercontent.com" in url:
                ok, msg, path = await self._download_from_google_drive(url, progress_callback)
                return ok, msg, path
            
            # Special handling for Pixeldrain links
            if "pixeldrain.com" in url:
                ok, msg, path = await self._download_from_pixeldrain(url, progress_callback)
                return ok, msg, path

            # Extract filename from URL
            filename = url.split('/')[-1].split('?')[0] or "downloaded_file"
            local_file_path = os.path.join(self.temp_dir, filename)
            
            logger.info(f"Starting download: {filename}")
            
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.timeout
            ) as client:
                # First, make a HEAD request to check file size before downloading
                head_response = await client.head(url)
                total_header = head_response.headers.get("Content-Length")
                total_size = int(total_header) if total_header and total_header.isdigit() else None
                
                if total_size is not None and total_size > self.max_size:
                    logger.info(f"File size {total_size} exceeds maximum allowed size {self.max_size}")
                    return False, f"❌ File `{filename}` is too large (> 2 GB).", None
                
                # Download file
                with open(local_file_path, 'wb') as f:
                    async with client.stream('GET', url) as response:
                        response.raise_for_status()

                        total_header = response.headers.get("Content-Length")
                        total_size = int(total_header) if total_header and total_header.isdigit() else None
                        
                        # Double check size after receiving response headers
                        if total_size is not None and total_size > self.max_size:
                            logger.info(f"File size {total_size} exceeds maximum allowed size {self.max_size}")
                            return False, f"❌ File `{filename}` is too large (> 2 GB).", None

                        downloaded = 0
                        start_time = time.monotonic()
                        last_update = start_time

                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)

                            # Throttle progress updates to ~1/sec
                            if progress_callback:
                                now = time.monotonic()
                                if now - last_update >= 1.0:
                                    elapsed = max(0.001, now - start_time)
                                    speed = downloaded / elapsed
                                    try:
                                        await progress_callback(downloaded, total_size, speed)
                                    except Exception as cb_err:
                                        logger.debug("Progress callback error (ignored): %s", cb_err)
                                    last_update = now

                        # Final progress update at completion
                        if progress_callback:
                            now = time.monotonic()
                            elapsed = max(0.001, now - start_time)
                            speed = downloaded / elapsed
                            try:
                                await progress_callback(downloaded, total_size, speed)
                            except Exception as cb_err:
                                logger.debug("Progress callback error (ignored): %s", cb_err)
            
            # Check file size as a final check
            file_size = os.path.getsize(local_file_path)
            logger.info(f"Downloaded {filename}: {file_size} bytes")
            
            if file_size > self.max_size:
                self.cleanup_file(local_file_path)
                return False, f"❌ File `{filename}` is too large (> 2 GB).", None
            
            return True, f"✅ File `{filename}` downloaded successfully.", local_file_path
            
        except httpx.RequestError as e:
            logger.error(f"Request error while downloading: {e}")
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, "❌ Download failed: Invalid URL or server not responding.", None
            
        except Exception as e:
            logger.error(f"Unexpected error while downloading: {e}", exc_info=True)
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, f"❌ There is an error: {str(e)}", None

    async def _download_from_google_drive(
        self,
        url: str,
        progress_callback: Optional[Callable[[int, Optional[int], float], Coroutine[Any, Any, None]]] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Download a file from Google Drive shared links.

        Supports formats like:
        - https://drive.google.com/file/d/<id>/view?...
        - https://drive.google.com/open?id=<id>
        - https://drive.google.com/uc?id=<id>&export=download
        And handles the confirmation token page for large files.
        """
        def _extract_id(u: str) -> Optional[str]:
            m = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", u)
            if m:
                return m.group(1)
            m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", u)
            if m:
                return m.group(1)
            return None

        file_id = _extract_id(url)
        logger.info(f"Google Drive link detected: {url}")
        initial_url = url
        if file_id:
            initial_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        local_file_path: Optional[str] = None
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                    "Referer": "https://drive.google.com",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            ) as client:
                # First request to get headers or confirm token page
                resp = await client.get(initial_url)
                resp.raise_for_status()

                def _filename_from_disposition(disposition: Optional[str]) -> Optional[str]:
                    if not disposition:
                        return None
                    # filename*=UTF-8''...
                    m = re.search(r"filename\*=UTF-8''([^;\r\n]+)", disposition)
                    if m:
                        from urllib.parse import unquote
                        return unquote(m.group(1))
                    m = re.search(r"filename=\"([^\"]+)\"", disposition)
                    if m:
                        return m.group(1)
                    m = re.search(r"filename=([^;\r\n]+)", disposition)
                    if m:
                        return m.group(1).strip()
                    return None

                cd = resp.headers.get("Content-Disposition")
                content_type = resp.headers.get("Content-Type", "")

                # If we already have a file response, stream it
                if cd and "attachment" in cd.lower() and not content_type.startswith("text/html"):
                    filename = _filename_from_disposition(cd) or (file_id or "downloaded_file")
                    local_file_path = os.path.join(self.temp_dir, filename)
                    total_header = resp.headers.get("Content-Length")
                    total_size = int(total_header) if total_header and total_header.isdigit() else None
                    downloaded = 0
                    start_time = time.monotonic()
                    last_update = start_time
                    with open(local_file_path, 'wb') as f:
                        async for chunk in resp.aiter_bytes():
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                now = time.monotonic()
                                if now - last_update >= 1.0:
                                    elapsed = max(0.001, now - start_time)
                                    speed = downloaded / elapsed
                                    try:
                                        await progress_callback(downloaded, total_size, speed)
                                    except Exception:
                                        pass
                                    last_update = now
                    # final update
                    if progress_callback:
                        now = time.monotonic()
                        elapsed = max(0.001, now - start_time)
                        speed = downloaded / elapsed
                        try:
                            await progress_callback(downloaded, total_size, speed)
                        except Exception:
                            pass
                else:
                    # Parse confirm token from HTML (large file / virus scan warning)
                    text = resp.text
                    def _extract_html_filename(html: str) -> Optional[str]:
                        # og:title
                        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                        if m:
                            return m.group(1)
                        # uc-name-size title attr
                        m = re.search(r'class=["\']uc-name-size["\'][^>]*title=["\']([^"\']+)["\']', html, re.IGNORECASE)
                        if m:
                            return m.group(1)
                        # data-title attr
                        m = re.search(r'data-title=["\']([^"\']+)["\']', html, re.IGNORECASE)
                        if m:
                            return m.group(1)
                        # <title>
                        m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                        if m:
                            title_text = m.group(1).strip()
                            # e.g., "recovery.img - Google Drive"
                            if ' - Google Drive' in title_text:
                                return title_text.split(' - Google Drive', 1)[0].strip()
                            return title_text
                        return None

                    def _sanitize_filename(name: str) -> str:
                        name = os.path.basename(name).strip().replace('\u200b', '')
                        name = name.replace('/', '_').replace('\\', '_').replace('\n', ' ').replace('\r', ' ')
                        # prevent empty names
                        return name or (file_id or 'downloaded_file')

                    candidate_name = _extract_html_filename(text)
                    if candidate_name:
                        candidate_name = _sanitize_filename(candidate_name)
                    token = None
                    # Try cookie-based token like gdown
                    try:
                        for k, v in resp.cookies.items():
                            if str(k).startswith("download_warning") and v:
                                token = str(v)
                                break
                    except Exception:
                        pass
                    m = re.search(r"confirm=([0-9A-Za-z_-]+)", text)
                    if m:
                        token = m.group(1)
                    if not token:
                        # Alternative hidden input pattern
                        m = re.search(r"name=\"confirm\"\s+value=\"([^\"]+)\"", text)
                        if m:
                            token = m.group(1)

                    # Fallback: try to follow the download link in page
                    dl_url = None
                    if token and file_id:
                        dl_url = f"https://drive.google.com/uc?export=download&confirm={token}&id={file_id}"
                    else:
                        # Try multiple patterns to find download link - capture full URLs with query params
                        patterns = [
                            # JSON-style download URL
                            r'"downloadUrl":\s*"([^"]+)"',
                            # Form action or href with full URL
                            r'href=["\']([^"\']+?usercontent\.google\.com/[^"\']+?)["\']',
                            r'href=["\']([^"\']+?googleusercontent\.com/[^"\']+?)["\']',
                            r'action=["\']([^"\']+?export=download[^"\']+?)["\']',
                            # Direct URL match with query params
                            r'(https://[^\s"\'<>]+?usercontent\.google\.com/[^\s"\'<>]+)',
                            r'(https://[^\s"\'<>]+?googleusercontent\.com/[^\s"\'<>]+)',
                        ]
                        for pattern in patterns:
                            m = re.search(pattern, text, re.IGNORECASE)
                            if m:
                                dl_url = m.group(1)
                                # Decode HTML entities
                                dl_url = dl_url.replace('&amp;', '&')
                                # Validate it looks complete
                                if 'id=' in dl_url or len(dl_url) > 100:
                                    break
                                else:
                                    dl_url = None

                    # If still no URL, try alternative direct download approach
                    if not dl_url and file_id:
                        # Try Google Drive API-style download
                        dl_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0&confirm=t"

                    if not dl_url:
                        return False, "❌ Failed to fetch file from Google Drive (token not found).", None

                    # Probe the confirmed URL to ensure it's a file, not HTML
                    probe = await client.get(dl_url)
                    probe.raise_for_status()
                    probe_ct = probe.headers.get("Content-Type", "")
                    probe_cd = probe.headers.get("Content-Disposition", "")
                    
                    if probe_ct.startswith("text/html"):
                        # Try to extract the final googleusercontent link from the page
                        html2 = probe.text
                        
                        # Try multiple patterns - ensure we capture full URL with query params
                        patterns2 = [
                            # Form action with full URL
                            r'<form[^>]+action=["\']([^"\']+usercontent\.google\.com/[^"\']+)["\']',
                            r'<form[^>]+action=["\']([^"\']+googleusercontent\.com/[^"\']+)["\']',
                            # Match href with full URL including query params
                            r'href=["\']([^"\']+usercontent\.google\.com/download[^"\']*)["\']',
                            r'href=["\']([^"\']+googleusercontent\.com/download[^"\']*)["\']',
                            # ID attribute for download link
                            r'id=["\']uc-download-link["\'][^>]+href=["\']([^"\']+)["\']',
                            # Generic patterns
                            r'href=["\']([^"\']+usercontent\.google\.com/[^"\']+?)["\']',
                            r'href=["\']([^"\']+googleusercontent\.com/[^"\']+?)["\']',
                            # Match URL without quotes - be more lenient with query params
                            r'(https://[^\s"\'<>]+usercontent\.google\.com/download[^\s"\'<>]*)',
                            r'(https://[^\s"\'<>]+googleusercontent\.com/download[^\s"\'<>]*)',
                        ]
                        for p2 in patterns2:
                            m2 = re.search(p2, html2, re.IGNORECASE)
                            if m2:
                                dl_url = m2.group(1)
                                # Decode HTML entities if present
                                dl_url = dl_url.replace('&amp;', '&')
                                # Remove trailing punctuation that might be captured
                                dl_url = dl_url.rstrip('.,;:!?)\']}"')
                                logger.info(f"Extracted final download URL: {dl_url}")
                                # Validate URL has required parameters
                                if 'id=' in dl_url or len(dl_url) > 100:  # Likely has params
                                    break
                                else:
                                    dl_url = None
                        
                        # If still no URL, parse form and build URL from hidden inputs
                        if not dl_url:
                            # Extract form action and build URL from hidden input fields
                            form_match = re.search(r'<form[^>]+action=["\']([^"\']+)["\'][^>]*>(.*?)</form>', html2, re.IGNORECASE | re.DOTALL)
                            if form_match:
                                form_action = form_match.group(1)
                                form_body = form_match.group(2)
                                
                                # Extract all hidden input fields
                                params = {}
                                for input_match in re.finditer(r'<input[^>]+name=["\']([^"\']+)["\'][^>]+value=["\']([^"\']+)["\']', form_body, re.IGNORECASE):
                                    params[input_match.group(1)] = input_match.group(2)
                                
                                # Also try reverse pattern (value before name)
                                for input_match in re.finditer(r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']([^"\']+)["\']', form_body, re.IGNORECASE):
                                    params[input_match.group(2)] = input_match.group(1)
                                
                                if params:
                                    # Build query string
                                    query_parts = [f"{k}={v}" for k, v in params.items()]
                                    query_string = "&".join(query_parts)
                                    dl_url = f"{form_action}?{query_string}"
                            
                            # Fallback: try to extract UUID and build URL manually
                            if not dl_url:
                                uuid_match = re.search(r'uuid["\']?\s*[:=]\s*["\']?([a-f0-9-]{36})["\']?', html2, re.IGNORECASE)
                                if uuid_match and file_id:
                                    uuid = uuid_match.group(1)
                                    dl_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0&confirm=t&uuid={uuid}"
                        
                        if not dl_url:
                            return False, "❌ Google Drive blocked direct download (no confirm link).", None
                    
                    # Check if we got a valid URL after HTML parsing
                    if not dl_url:
                        return False, "❌ Google Drive blocked direct download (no confirm link).", None

                    # First, check file size before downloading
                    size_check_response = await client.head(dl_url)
                    total_header = size_check_response.headers.get("Content-Length")
                    total_size = int(total_header) if total_header and total_header.isdigit() else None
                    
                    if total_size is not None and total_size > self.max_size:
                        logger.info(f"File size {total_size} exceeds maximum allowed size {self.max_size}")
                        return False, "❌ File is too large (> 2 GB).", None

                    # Stream the final confirmed URL
                    async with client.stream("GET", dl_url) as stream:
                        stream.raise_for_status()
                        cd2 = stream.headers.get("Content-Disposition")
                        filename = _filename_from_disposition(cd2) or candidate_name or (file_id or "downloaded_file")
                        # Avoid misleading HTML titles
                        if filename.lower().startswith("google drive - virus"):
                            filename = file_id or "downloaded_file"
                        local_file_path = os.path.join(self.temp_dir, filename)
                        total_header = stream.headers.get("Content-Length")
                        total_size = int(total_header) if total_header and total_header.isdigit() else None
                        
                        # Double check size after receiving response headers
                        if total_size is not None and total_size > self.max_size:
                            logger.info(f"File size {total_size} exceeds maximum allowed size {self.max_size}")
                            return False, "❌ File is too large (> 2 GB).", None

                        downloaded = 0
                        start_time = time.monotonic()
                        last_update = start_time
                        with open(local_file_path, 'wb') as f:
                            async for chunk in stream.aiter_bytes():
                                if not chunk:
                                    continue
                                f.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback:
                                    now = time.monotonic()
                                    if now - last_update >= 1.0:
                                        elapsed = max(0.001, now - start_time)
                                        speed = downloaded / elapsed
                                        try:
                                            await progress_callback(downloaded, total_size, speed)
                                        except Exception:
                                            pass
                                        last_update = now
                        if progress_callback:
                            now = time.monotonic()
                            elapsed = max(0.001, now - start_time)
                            speed = downloaded / elapsed
                            try:
                                await progress_callback(downloaded, total_size, speed)
                            except Exception:
                                pass

            if not local_file_path or not os.path.exists(local_file_path):
                return False, "❌ Failed to download from Google Drive.", None

            file_size = os.path.getsize(local_file_path)
            
            # Validate that we didn't download an HTML error page
            if file_size < 1024:  # Files smaller than 1KB are suspicious
                try:
                    with open(local_file_path, 'rb') as f:
                        first_bytes = f.read(512)
                        if b'<!DOCTYPE' in first_bytes or b'<html' in first_bytes.lower():
                            self.cleanup_file(local_file_path)
                        return False, "❌ Google Drive: File is not accessible. Ensure the sharing link is set to 'Anyone with the link'.", None
                except Exception as e:
                    logger.error(f"Error validating downloaded file: {e}")
            
            if file_size > self.max_size:
                self.cleanup_file(local_file_path)
                return False, "❌ File is too large (> 2 GB).", None

            filename = os.path.basename(local_file_path)
            logger.info(f"Downloaded file from Google Drive: {filename} ({_format_size(file_size)})")
            return True, f"✅ File `{filename}` downloaded successfully.", local_file_path

        except httpx.RequestError as e:
            logger.error(f"Request error while downloading from Google Drive: {e}")
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, "❌ Download failed: Google Drive not reachable.", None
        except Exception as e:
            logger.error(f"Unexpected error while downloading from Google Drive: {e}", exc_info=True)
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, f"❌ There is an error: {str(e)}", None

    async def _download_from_pixeldrain(
        self,
        url: str,
        progress_callback: Optional[Callable[[int, Optional[int], float], Coroutine[Any, Any, None]]] = None,
        filename_callback: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Download a file from Pixeldrain.
        
        Supports formats like:
        - https://pixeldrain.com/u/FILE_ID
        - https://pixeldrain.com/api/file/FILE_ID
        """
        def _extract_pixeldrain_id(u: str) -> Optional[str]:
            # Extract ID from various Pixeldrain URL formats
            import re
            patterns = [
                r'pixeldrain\.com/u/([a-zA-Z0-9_-]+)',
                r'pixeldrain\.com/api/file/([a-zA-Z0-9_-]+)',
            ]
            for pattern in patterns:
                m = re.search(pattern, u)
                if m:
                    return m.group(1)
            return None

        file_id = _extract_pixeldrain_id(url)
        if not file_id:
            return False, "❌ Invalid Pixeldrain URL format.", None
        
        logger.info(f"Pixeldrain link detected: {url}")
        
        # Use Pixeldrain API for download
        api_url = f"https://pixeldrain.com/api/file/{file_id}"
        info_url = f"https://pixeldrain.com/api/file/{file_id}/info"
        
        local_file_path: Optional[str] = None
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                },
            ) as client:
                # First get file info to determine filename and size
                try:
                    info_resp = await client.get(info_url)
                    info_resp.raise_for_status()
                    file_info = info_resp.json()
                    filename = file_info.get('name', f'pixeldrain_{file_id}')
                    expected_size = file_info.get('size')
                    
                    # Notify caller about real filename for banner update
                    if filename_callback:
                        try:
                            await filename_callback(filename)
                        except Exception:
                            pass
                            
                except Exception:
                    # If info fails, use fallback filename
                    filename = f'pixeldrain_{file_id}'
                    expected_size = None
                
                local_file_path = os.path.join(self.temp_dir, filename)
                
                # First, check file size before downloading
                size_check_response = await client.head(api_url)
                total_header = size_check_response.headers.get("Content-Length")
                total_size = int(total_header) if total_header and total_header.isdigit() else expected_size
                
                if total_size is not None and total_size > self.max_size:
                    logger.info(f"File size {total_size} exceeds maximum allowed size {self.max_size}")
                    return False, f"❌ File `{filename}` is too large (> 2 GB).", None
                
                # Download the file
                with open(local_file_path, 'wb') as f:
                    async with client.stream('GET', api_url) as response:
                        response.raise_for_status()
                        
                        total_header = response.headers.get("Content-Length")
                        total_size = int(total_header) if total_header and total_header.isdigit() else expected_size
                        
                        # Double check size after receiving response headers
                        if total_size is not None and total_size > self.max_size:
                            logger.info(f"File size {total_size} exceeds maximum allowed size {self.max_size}")
                            return False, f"❌ File `{filename}` is too large (> 2 GB).", None

                        downloaded = 0
                        start_time = time.monotonic()
                        last_update = start_time

                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)

                            # Throttle progress updates to ~1/sec
                            if progress_callback:
                                now = time.monotonic()
                                if now - last_update >= 1.0:
                                    elapsed = max(0.001, now - start_time)
                                    speed = downloaded / elapsed
                                    try:
                                        await progress_callback(downloaded, total_size, speed)
                                    except Exception:
                                        pass
                                    last_update = now

                        # Final progress update at completion
                        if progress_callback:
                            now = time.monotonic()
                            elapsed = max(0.001, now - start_time)
                            speed = downloaded / elapsed
                            try:
                                await progress_callback(downloaded, total_size, speed)
                            except Exception:
                                pass
                
                # Check file size as a final check
                file_size = os.path.getsize(local_file_path)
                
                if file_size > self.max_size:
                    self.cleanup_file(local_file_path)
                    return False, f"❌ File `{filename}` is too large (> 2 GB).", None
                
                logger.info(f"Downloaded file from Pixeldrain: {filename} ({_format_size(file_size)})")
                return True, f"✅ File `{filename}` downloaded successfully.", local_file_path
                
        except httpx.RequestError as e:
            logger.error(f"Request error while downloading from Pixeldrain: {e}")
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, "❌ Download failed: Pixeldrain server not reachable.", None
        
        except Exception as e:
            logger.error(f"Unexpected error while downloading from Pixeldrain: {e}", exc_info=True)
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, f"❌ There is an error: {str(e)}", None
    
    async def download_audio(
        self,
        url: str,
        progress_callback: Optional[Callable[[int, Optional[int], Optional[float], Optional[float]], Coroutine[Any, Any, None]]] = None,
    ) -> Tuple[bool, str, Optional[str], Optional[Dict[str, Optional[str]]]]:
        """
        Download audio content using yt-dlp.

        Returns a tuple of (success, message, file_path, metadata).
        """
        local_file_path: Optional[str] = None
        metadata: Optional[Dict[str, Optional[str]]] = None

        def _normalize_url(original_url: str) -> str:
            if "music.youtube.com" in original_url:
                return original_url.replace("music.youtube.com", "www.youtube.com", 1)
            return original_url

        normalized_url = _normalize_url(url)

        def _prepare_cookie_file() -> Optional[str]:
            if not self.cookie_file_path:
                return None
            try:
                with open(self.cookie_file_path, 'rb') as src:
                    temp_file = tempfile.NamedTemporaryFile(
                        dir=self.temp_dir, suffix=".cookies", delete=False
                    )
                    with temp_file:
                        shutil.copyfileobj(src, temp_file)
                    return temp_file.name
            except Exception as cookie_error:
                logger.error("Failed to prepare cookie file: %s", cookie_error, exc_info=True)
                return None

        # Capture the current asyncio loop to be used from the worker thread
        try:
            current_loop = asyncio.get_running_loop() if progress_callback else None
        except RuntimeError:
            current_loop = None

        def _download(cookiefile: Optional[str]) -> Tuple[Any, Optional[str]]:
            ydl_opts: Any = {
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": os.path.join(self.temp_dir, "%(title)s.%(ext)s"),
                "restrictfilenames": True,
                "nocheckcertificate": True,
                "quiet": True,
                "noprogress": True,
                "cachedir": False,
                "noplaylist": True,
            }

            if self.ffmpeg_available:
                ydl_opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ]
            else:
                ydl_opts["prefer_ffmpeg"] = False

            if cookiefile:
                ydl_opts["cookiefile"] = cookiefile

            # Prepare progress hook bridging from thread to asyncio loop
            if progress_callback is not None:
                non_optional_callback = progress_callback
                last_sent = {"t": 0.0}

                def _hook(d: Dict[str, Any]):
                    status = d.get("status")
                    now = time.monotonic()
                    if status == "downloading":
                        downloaded = int(d.get("downloaded_bytes") or 0)
                        total = d.get("total_bytes") or d.get("total_bytes_estimate")
                        total_int = int(total) if isinstance(total, (int, float)) else None
                        speed = d.get("speed")
                        eta = d.get("eta")
                        if now - last_sent["t"] < 1.0:
                            return
                        last_sent["t"] = now
                        if current_loop is not None:
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    non_optional_callback(downloaded, total_int, float(speed) if speed else None, float(eta) if eta else None),
                                    current_loop,
                                )
                            except Exception:
                                pass
                    elif status == "finished":
                        # Ensure we push a final 100% update so UI doesn't look stuck at ~97%
                        downloaded = int(
                            d.get("total_bytes")
                            or d.get("downloaded_bytes")
                            or d.get("total_bytes_estimate")
                            or 0
                        )
                        total_int = downloaded if downloaded > 0 else None
                        if current_loop is not None:
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    non_optional_callback(downloaded, total_int, None, 0.0),
                                    current_loop,
                                )
                            except Exception:
                                pass

                ydl_opts["progress_hooks"] = [_hook]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info: Any = ydl.extract_info(normalized_url, download=True)
                file_path: Optional[str] = None
                requested = info.get("requested_downloads") or []
                if requested:
                    file_path = requested[0].get("filepath")
                elif "_filename" in info:
                    file_path = info["_filename"]
                return info, file_path

        try:
            temp_cookie = _prepare_cookie_file()
            try:
                info, local_file_path = await asyncio.to_thread(_download, temp_cookie)
            finally:
                if temp_cookie:
                    self.cleanup_file(temp_cookie)

            if not local_file_path or not os.path.exists(local_file_path):
                logger.error("yt-dlp did not return a valid file path")
                return False, "❌ Failed to download audio.", None, None

            file_size = os.path.getsize(local_file_path)
            logger.info(f"Downloaded audio file: {local_file_path} ({file_size} bytes)")

            if file_size > self.max_size:
                self.cleanup_file(local_file_path)
                return False, "❌ Audio file is too large (> 2 GB).", None, None

            metadata = {
                "title": info.get("title") if isinstance(info.get("title"), str) else None,
                "duration": str(info.get("duration")) if info.get("duration") is not None else None,
            }

            display_name = metadata.get("title") or os.path.basename(local_file_path)
            return True, f"✅ Audio `{display_name}` downloaded successfully.", local_file_path, metadata

        except DownloadError as e:
            logger.error(f"yt-dlp download error: {e}")
            if local_file_path:
                self.cleanup_file(local_file_path)

            error_message = str(e).lower()
            if "ffmpeg" in error_message or "ffprobe" in error_message:
                return False, "❌ Failed to download audio: Server does not have FFmpeg installed, contact admin to install it.", None, None
            if "confirm your age" in error_message or "age" in error_message:
                return False, "❌ Failed to download audio: Video is age restricted and requires a signed in account..", None, None

            detail = str(e).strip()
            if detail:
                return False, f"❌ Failed to download audio: {detail}", None, None
            return False, "❌ Failed to download audio: Invalid URL or content unavailable.", None, None
        except Exception as e:
            logger.error(f"Unexpected error during audio download: {e}", exc_info=True)
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, f"❌ There is an error: {str(e)}", None, None

    def cleanup_file(self, file_path: str):
        """
        Clean up temporary file.
        
        Args:
            file_path: Path to file to delete
        """
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up temp file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")

    def cleanup_temp_directory(self) -> Tuple[int, int, int]:
        """Remove all files and directories inside the temp directory."""
        files_removed = 0
        dirs_removed = 0
        errors = 0

        if not os.path.exists(self.temp_dir):
            return files_removed, dirs_removed, errors

        try:
            for entry in os.scandir(self.temp_dir):
                path = entry.path
                try:
                    if entry.is_symlink() or entry.is_file():
                        os.unlink(path)
                        files_removed += 1
                    elif entry.is_dir():
                        shutil.rmtree(path)
                        dirs_removed += 1
                except Exception as cleanup_error:
                    errors += 1
                    logger.error(f"Failed to remove {path}: {cleanup_error}", exc_info=True)
        except Exception as scan_error:
            errors += 1
            logger.error(f"Failed to scan temp directory {self.temp_dir}: {scan_error}", exc_info=True)

        return files_removed, dirs_removed, errors

# Global file service instance
file_service = FileService()
