"""AI service for handling AI model interactions"""
from typing import Dict, List, Optional, cast

import httpx
from config.settings import (
    BYTEZ_API_KEY,
    BYTEZ_API_URL,
    BYTEZ_TIMEOUT,
    AI_MAX_LENGTH,
    AI_TEMPERATURE,
    AI_SYSTEM_PROMPT
)
from utils.logger import setup_logger
from utils.markdown import clean_ai_response

logger = setup_logger(__name__)

class AIService:
    """Service for interacting with AI models"""
    
    def __init__(self):
        self.api_key = cast(str, BYTEZ_API_KEY)
        self.api_url = cast(str, BYTEZ_API_URL)
        self.timeout = BYTEZ_TIMEOUT
    
    async def get_response(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Get AI response for user message.
        
        Args:
            user_message: User's message
            conversation_history: Optional conversation history
            
        Returns:
            AI response text
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                logger.info(f"Sending request to AI API")
                
                # Build messages
                messages = [
                    {"role": "system", "content": AI_SYSTEM_PROMPT}
                ]
                
                # Add conversation history if provided
                if conversation_history:
                    messages.extend(conversation_history[-10:])  # Last 10 messages
                
                # Add current user message
                messages.append({"role": "user", "content": user_message})
                
                headers: Dict[str, str] = {
                    "Authorization": self.api_key,
                    "Content-Type": "application/json"
                }

                response = await client.post(
                    url=self.api_url,
                    headers=headers,
                    json={
                        "messages": messages,
                        "stream": False,
                        "params": {
                            "max_length": AI_MAX_LENGTH,
                            "temperature": AI_TEMPERATURE
                        }
                    }
                )
                
                logger.info(f"Received response, status: {response.status_code}")
                response.raise_for_status()
                
                data = response.json()
                
                # Extract content from response
                output = data.get('output', '')
                if isinstance(output, dict) and 'content' in output:
                    content = output['content']
                elif isinstance(output, str):
                    content = output
                else:
                    content = str(output)
                
                # Clean the response
                content = clean_ai_response(content)
                
                if not content or content.strip() == "":
                    logger.warning("Empty response from AI")
                    return "Maaf, tidak ada response dari AI. Coba lagi."
                
                logger.info(f"Response length: {len(content)} characters")
                return content.strip()
                
            except httpx.TimeoutException:
                logger.error("Timeout while contacting AI API")
                return "⏱️ AI membutuhkan waktu terlalu lama untuk merespons. Coba lagi nanti."
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error from AI API: {e.response.status_code}")
                logger.debug(f"Response body: {e.response.text}")
                
                if e.response.status_code == 401:
                    return "🔒 Kesalahan otentikasi. API Key tidak valid."
                elif e.response.status_code == 429:
                    return "⚠️ Terlalu banyak permintaan. Coba lagi sesaat."
                else:
                    return f"❌ Terjadi kesalahan saat menghubungi AI (HTTP {e.response.status_code})."
                    
            except Exception as e:
                logger.error(f"Unexpected error in AI service: {e}", exc_info=True)
                return "❌ Terjadi masalah internal. Coba lagi nanti."

# Global AI service instance
ai_service = AIService()
