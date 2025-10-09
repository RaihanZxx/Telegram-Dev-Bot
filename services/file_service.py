"""File service for downloading and handling files"""
import asyncio
import os
from typing import Dict, Optional, Tuple

import httpx
import yt_dlp
from yt_dlp.utils import DownloadError
from config.settings import TEMP_DIR, MAX_FILE_SIZE, DOWNLOAD_TIMEOUT
from utils.logger import setup_logger

logger = setup_logger(__name__)

class FileService:
    """Service for file operations"""
    
    def __init__(self):
        self.temp_dir = TEMP_DIR
        self.max_size = MAX_FILE_SIZE
        self.timeout = DOWNLOAD_TIMEOUT
        
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
                return False, f"❌ File `{filename}` terlalu besar (> 1 GB).", None
            
            return True, f"✅ File `{filename}` berhasil diunduh.", local_file_path
            
        except httpx.RequestError as e:
            logger.error(f"Request error while downloading: {e}")
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, "❌ Gagal mengunduh: URL tidak valid atau server tidak merespons.", None
            
        except Exception as e:
            logger.error(f"Unexpected error while downloading: {e}", exc_info=True)
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, f"❌ Terjadi kesalahan: {str(e)}", None
    
    async def download_audio(self, url: str) -> Tuple[bool, str, Optional[str], Optional[Dict[str, Optional[str]]]]:
        """
        Download audio content using yt-dlp.

        Returns a tuple of (success, message, file_path, metadata).
        """
        local_file_path: Optional[str] = None
        metadata: Optional[Dict[str, Optional[str]]] = None

        def _download() -> Tuple[Dict, Optional[str]]:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(self.temp_dir, "%(title)s.%(ext)s"),
                "restrictfilenames": True,
                "nocheckcertificate": True,
                "quiet": True,
                "noprogress": True,
                "cachedir": False,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = None
                requested = info.get("requested_downloads") or []
                if requested:
                    file_path = requested[0].get("filepath")
                elif "_filename" in info:
                    file_path = info["_filename"]
                return info, file_path

        try:
            info, local_file_path = await asyncio.to_thread(_download)

            if not local_file_path or not os.path.exists(local_file_path):
                logger.error("yt-dlp did not return a valid file path")
                return False, "❌ Gagal mengunduh audio.", None, None

            file_size = os.path.getsize(local_file_path)
            logger.info(f"Downloaded audio file: {local_file_path} ({file_size} bytes)")

            if file_size > self.max_size:
                self.cleanup_file(local_file_path)
                return False, "❌ File audio terlalu besar (> 1 GB).", None, None

            metadata = {
                "title": info.get("title"),
                "duration": str(info.get("duration")) if info.get("duration") else None,
            }

            display_name = metadata.get("title") or os.path.basename(local_file_path)
            return True, f"✅ Audio `{display_name}` berhasil diunduh.", local_file_path, metadata

        except DownloadError as e:
            logger.error(f"yt-dlp download error: {e}")
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, "❌ Gagal mengunduh audio: URL tidak valid atau konten tidak tersedia.", None, None
        except Exception as e:
            logger.error(f"Unexpected error during audio download: {e}", exc_info=True)
            if local_file_path:
                self.cleanup_file(local_file_path)
            return False, f"❌ Terjadi kesalahan: {str(e)}", None, None

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

# Global file service instance
file_service = FileService()
