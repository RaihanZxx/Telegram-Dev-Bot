"""File service for downloading and handling files"""
import asyncio
import os
import re
import shutil
import tempfile
import time
from typing import Any, Callable, Optional, Tuple, Dict, Awaitable

import httpx
import yt_dlp
from yt_dlp.utils import DownloadError
from config.settings import TEMP_DIR, MAX_FILE_SIZE, DOWNLOAD_TIMEOUT, YT_COOKIES_FILE
from utils.logger import setup_logger

logger = setup_logger(__name__)

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
        progress_callback: Optional[Callable[[int, Optional[int], float], Awaitable[None]]] = None,
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

            # Extract filename from URL
            filename = url.split('/')[-1].split('?')[0] or "downloaded_file"
            local_file_path = os.path.join(self.temp_dir, filename)
            
            logger.info(f"Starting download: {filename}")
            
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.timeout
            ) as client:
                # Download file
                with open(local_file_path, 'wb') as f:
                    async with client.stream('GET', url) as response:
                        response.raise_for_status()

                        total_header = response.headers.get("Content-Length")
                        total_size = int(total_header) if total_header and total_header.isdigit() else None
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
            
            # Check file size
            file_size = os.path.getsize(local_file_path)
            logger.info(f"Downloaded {filename}: {file_size} bytes")
            
            if file_size > self.max_size:
                self.cleanup_file(local_file_path)
                return False, f"❌ File `{filename}` terlalu besar (> 2 GB).", None
            
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
        progress_callback: Optional[Callable[[int, Optional[int], float], Awaitable[None]]] = None,
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
        initial_url = url
        if file_id:
            initial_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        local_file_path: Optional[str] = None
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
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
                    token = None
                    m = re.search(r"confirm=([0-9A-Za-z_]+)", text)
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
                        # Try to find a direct docs.googleusercontent.com link
                        m = re.search(r'https://[^\"]+?googleusercontent.com/[^\"]+', text)
                        if m:
                            dl_url = m.group(0)

                    if not dl_url:
                        return False, "❌ Failed to fetch file from Google Drive (token not found).", None

                    # Stream the final confirmed URL
                    async with client.stream("GET", dl_url) as stream:
                        stream.raise_for_status()
                        cd2 = stream.headers.get("Content-Disposition")
                        filename = _filename_from_disposition(cd2) or (file_id or "downloaded_file")
                        local_file_path = os.path.join(self.temp_dir, filename)
                        total_header = stream.headers.get("Content-Length")
                        total_size = int(total_header) if total_header and total_header.isdigit() else None
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
            if file_size > self.max_size:
                self.cleanup_file(local_file_path)
                return False, "❌ File terlalu besar (> 2 GB).", None

            filename = os.path.basename(local_file_path)
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
    
    async def download_audio(
        self,
        url: str,
        progress_callback: Optional[Callable[[int, Optional[int], Optional[float], Optional[float]], Awaitable[None]]] = None,
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
                                    progress_callback(downloaded, total_int, float(speed) if speed else None, float(eta) if eta else None),
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
                                    progress_callback(downloaded, total_int, None, 0.0),
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
