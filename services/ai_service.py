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
                
                # Build a single text prompt (Bytez v2 commonly expects `input`)
                parts: List[str] = [f"[system] {AI_SYSTEM_PROMPT}"]
                if conversation_history:
                    for m in conversation_history[-10:]:
                        role = m.get("role", "user")
                        content = m.get("content", "")
                        parts.append(f"[{role}] {content}")
                parts.append(f"[user] {user_message}")
                prompt = "\n".join(parts)

                # Also prepare messages schema for fallback
                messages: List[Dict[str, str]] = [{"role": "system", "content": AI_SYSTEM_PROMPT}]
                if conversation_history:
                    messages.extend(conversation_history[-10:])
                messages.append({"role": "user", "content": user_message})

                def _headers(style: str) -> Dict[str, str]:
                    if style == "raw":
                        return {
                            "Authorization": self.api_key,
                            "Content-Type": "application/json",
                        }
                    return {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    }

                # Primary schema: OpenAI-like messages with top-level params
                payload = {
                    "messages": messages,
                    "stream": False,
                    "max_tokens": AI_MAX_LENGTH,
                    "temperature": AI_TEMPERATURE,
                }

                # First try with raw Authorization header (matches image_service)
                response = await client.post(
                    url=self.api_url,
                    headers=_headers("raw"),
                    json=payload,
                )
                
                logger.info(f"Received response, status: {response.status_code}")
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as first_err:
                    if first_err.response.status_code == 401:
                        # Retry once with Bearer token style
                        logger.info("AI API 401 with raw auth: retrying with Bearer token")
                        retry = await client.post(
                            url=self.api_url,
                            headers=_headers("bearer"),
                            json=payload,
                        )
                        logger.info(f"Bearer retry status: {retry.status_code}")
                        retry.raise_for_status()
                        data = retry.json()
                    elif first_err.response.status_code == 422:
                        # Fallback A: messages + params nesting
                        logger.info("AI API 422: retrying with messages + params schema")
                        alt_payload = {
                            "messages": messages,
                            "stream": False,
                            "params": {
                                "max_tokens": AI_MAX_LENGTH,
                                "temperature": AI_TEMPERATURE,
                            },
                        }
                        alt = await client.post(
                            url=self.api_url,
                            headers=_headers("raw"),
                            json=alt_payload,
                        )
                        logger.info(f"Received alt response, status: {alt.status_code}")
                        alt.raise_for_status()
                        try:
                            data = alt.json()
                        except Exception:
                            data = {"output": alt.text}
                        
                        # If still invalid in practice, try Fallback B: input + top-level params
                        if not data:
                            alt_b = await client.post(
                                url=self.api_url,
                                headers=_headers("raw"),
                                json={
                                    "input": prompt,
                                    "stream": False,
                                    "max_tokens": AI_MAX_LENGTH,
                                    "temperature": AI_TEMPERATURE,
                                },
                            )
                            logger.info("Received alt B response, status: %s", alt_b.status_code)
                            alt_b.raise_for_status()
                            try:
                                data = alt_b.json()
                            except Exception:
                                data = {"output": alt_b.text}
                    else:
                        raise
                else:
                    data = response.json()
                
                # Extract content from response (robust across formats)
                def _get_first_text(obj) -> str:
                    if obj is None:
                        return ""
                    if isinstance(obj, str):
                        return obj
                    if isinstance(obj, dict):
                        for k in (
                            "content",
                            "text",
                            "message",
                            "output",
                            "response",
                            "result",
                            "generated_text",
                        ): 
                            v = obj.get(k)
                            s = _get_first_text(v)
                            if s:
                                return s
                        # OpenAI-like choices
                        choices = obj.get("choices")
                        if isinstance(choices, list) and choices:
                            ch0 = choices[0]
                            if isinstance(ch0, dict):
                                msg = ch0.get("message") or {}
                                s = _get_first_text(msg)
                                if s:
                                    return s
                                s = _get_first_text(ch0.get("text"))
                                if s:
                                    return s
                        # nested data
                        data_field = obj.get("data")
                        s = _get_first_text(data_field)
                        if s:
                            return s
                        return ""
                    if isinstance(obj, (list, tuple)):
                        for it in obj:
                            s = _get_first_text(it)
                            if s:
                                return s
                        return ""
                    return ""

                content = _get_first_text(data)
                if not content:
                    try:
                        keys = list(data.keys()) if isinstance(data, dict) else [type(data).__name__]
                        logger.info("Extraction empty; response keys=%s", keys)
                    except Exception:
                        pass

                    # Retry with input primary (top-level params)
                    try:
                        alt1 = await client.post(
                            url=self.api_url,
                            headers=_headers("raw"),
                            json={
                                "input": prompt,
                                "stream": False,
                                "max_tokens": AI_MAX_LENGTH,
                                "temperature": AI_TEMPERATURE,
                            },
                        )
                        logger.info("Input schema status: %s", alt1.status_code)
                        alt1.raise_for_status()
                        data_alt1 = alt1.json()
                        content = _get_first_text(data_alt1)
                    except httpx.HTTPStatusError as _:
                        content = content or ""

                    # If still empty, try input + params nesting
                    if not content:
                        try:
                            alt2 = await client.post(
                                url=self.api_url,
                                headers=_headers("raw"),
                                json={
                                    "input": prompt,
                                    "stream": False,
                                    "params": {
                                        "max_tokens": AI_MAX_LENGTH,
                                        "temperature": AI_TEMPERATURE,
                                    },
                                },
                            )
                            logger.info("Input schema (params) status: %s", alt2.status_code)
                            alt2.raise_for_status()
                            data_alt2 = alt2.json()
                            content = _get_first_text(data_alt2)
                        except httpx.HTTPStatusError as _:
                            content = content or ""

                # If still empty, last resort: include raw text body to attempt extraction
                if not content:
                    try:
                        # This will only be available if last request object is named alt2 or response
                        # but ensure we don't crash if not present.
                        logger.info("AI response still empty after fallbacks")
                    except Exception:
                        pass
                
                # Clean and sanitize response to avoid leaking prompt/roles
                content = clean_ai_response(content)
                try:
                    # Remove any leaked system prompt and role-tag lines
                    if AI_SYSTEM_PROMPT:
                        content = content.replace(AI_SYSTEM_PROMPT, "")
                    lines = [
                        ln for ln in content.splitlines()
                        if not ln.strip().startswith("[system]")
                        and not ln.strip().startswith("[user]")
                        and not ln.strip().startswith("[assistant]")
                    ]
                    content = "\n".join(lines)
                except Exception:
                    pass
                
                if not content or content.strip() == "":
                    logger.warning("Empty response from AI")
                    return "Sorry, the AI did not respond. Please try again."
                
                logger.info(f"Response length: {len(content)} characters")
                return content.strip()
                
            except httpx.TimeoutException:
                logger.error("Timeout while contacting AI API")
                return "⏱️ AI is taking too long to respond. Please try again later."
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error from AI API: {e.response.status_code}")
                logger.debug(f"Response body: {e.response.text}")
                
                if e.response.status_code == 401:
                    return "🔒 Authentication error. Invalid API Key."
                elif e.response.status_code == 429:
                    return "⚠️ Too many requests. Please try again later."
                elif e.response.status_code == 422:
                    return "❌ The AI request was rejected (422). Please try again or rephrase your prompt."
                else:
                    return f"❌ An error occurred while contacting AI (HTTP {e.response.status_code})."
                    
            except Exception as e:
                logger.error(f"Unexpected error in AI service: {e}", exc_info=True)
                return "❌ An internal problem occurred. Please try again later."

# Global AI service instance
ai_service = AIService()
