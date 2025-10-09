"""Image generation service using Bytez models"""
import base64
from io import BytesIO
from typing import Optional

import httpx

from config.settings import (
    BYTEZ_API_KEY,
    BYTEZ_IMAGE_MODEL_URL,
    BYTEZ_IMAGE_TIMEOUT,
)
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ImageService:
    """Service for interacting with Bytez text-to-image models"""

    def __init__(self) -> None:
        self.api_key = BYTEZ_API_KEY
        self.api_url = BYTEZ_IMAGE_MODEL_URL
        self.timeout = BYTEZ_IMAGE_TIMEOUT

    async def generate_image(self, prompt: str) -> Optional[BytesIO]:
        """Generate an image from the provided prompt"""
        if not prompt or not prompt.strip():
            logger.warning("Image prompt is empty")
            return None

        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                logger.info("Submitting image generation request")
                response = await client.post(
                    url=self.api_url,
                    headers=headers,
                    json={
                        "input": prompt.strip(),
                        "stream": False,
                    },
                )
                logger.info("Image generation response status: %s", response.status_code)
                response.raise_for_status()

                data = response.json()
                output = data.get("output")

                image_bytes = await self._extract_image_bytes(client, output)
                if image_bytes is None:
                    logger.error("Failed to parse image output from Bytez")
                    return None

                buffer = BytesIO(image_bytes)
                buffer.name = "generated.png"
                buffer.seek(0)
                return buffer

            except httpx.TimeoutException:
                logger.error("Timeout while contacting image generation API")
                return None
            except httpx.HTTPStatusError as exc:
                logger.error("HTTP error from image generation API: %s", exc.response.status_code)
                logger.debug("Image API error body: %s", exc.response.text)
                return None
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error from image generation API: %s", exc, exc_info=True)
                return None

    async def _extract_image_bytes(self, client: httpx.AsyncClient, output) -> Optional[bytes]:
        """Extract image bytes from the API output"""
        if output is None:
            return None

        if isinstance(output, (list, tuple)):
            for item in output:
                resolved = await self._resolve_item(client, item)
                if resolved:
                    return resolved
            return None

        return await self._resolve_item(client, output)

    async def _resolve_item(self, client: httpx.AsyncClient, item) -> Optional[bytes]:
        """Resolve a single output item into image bytes"""
        if isinstance(item, dict):
            for key in ("url", "image", "content", "data"):
                value = item.get(key)
                if isinstance(value, str):
                    resolved = await self._handle_string(client, value)
                    if resolved:
                        return resolved

            for key in ("base64", "image_base64", "b64"):
                value = item.get(key)
                if isinstance(value, str):
                    decoded = self._decode_base64(value)
                    if decoded:
                        return decoded
            return None

        if isinstance(item, str):
            return await self._handle_string(client, item)

        return None

    async def _handle_string(self, client: httpx.AsyncClient, value: str) -> Optional[bytes]:
        """Handle string outputs as either URLs or base64"""
        text = value.strip()
        if text.startswith("http://") or text.startswith("https://"):
            try:
                logger.info("Downloading generated image from URL")
                response = await client.get(text)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as exc:
                logger.error("Failed to download image from URL: %s", exc)
                return None

        decoded = self._decode_base64(text)
        if decoded:
            return decoded

        return None

    def _decode_base64(self, value: str) -> Optional[bytes]:
        """Decode base64 data into bytes"""
        try:
            return base64.b64decode(value)
        except Exception:  # noqa: BLE001
            return None


image_service = ImageService()
