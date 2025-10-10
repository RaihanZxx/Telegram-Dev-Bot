"""File service for downloading and handling files"""
import asyncio
import os
import shutil
import tempfile
from typing import Any, Dict, Optional, Tuple

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
    
    async def download_file(self, url: str) -> Tuple[bool, str, Optional[str]]:
        """
        Download file from URL.
        
        Args:
            url: File URL
            
        Returns:
            Tuple of (success, message, local_file_path)
        """
        local_file_path = None
        
        try:
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
                        
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
            
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
    
    async def download_audio(self, url: str) -> Tuple[bool, str, Optional[str], Optional[Dict[str, Optional[str]]]]:
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
