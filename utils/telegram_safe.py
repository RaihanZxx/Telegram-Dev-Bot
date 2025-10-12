import asyncio
import random
from typing import Any, Dict, Optional

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

_locks: Dict[int, asyncio.Lock] = {}


def _get_lock(chat_id: int) -> asyncio.Lock:
    lock = _locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[chat_id] = lock
    return lock


async def _with_retry(func, *args, max_retries: int = 4, **kwargs):
    attempt = 0
    while True:
        try:
            return await func(*args, **kwargs)
        except RetryAfter as e:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = float(getattr(e, "retry_after", 1)) + random.uniform(0.1, 0.6)
            await asyncio.sleep(delay)


async def edit_message_text_safe(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    parse_mode: Optional[ParseMode | str] = None,
    max_retries: int = 4,
):
    lock = _get_lock(chat_id)
    async with lock:
        return await _with_retry(
            bot.edit_message_text,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            max_retries=max_retries,
        )


async def edit_text_safe(
    message: Message,
    text: str,
    *,
    parse_mode: Optional[ParseMode | str] = None,
    max_retries: int = 4,
):
    chat_id = message.chat.id
    lock = _get_lock(chat_id)
    async with lock:
        return await _with_retry(
            message.edit_text,
            text,
            parse_mode=parse_mode,
            max_retries=max_retries,
        )


async def reply_text_safe(
    message: Message,
    text: str,
    *,
    parse_mode: Optional[ParseMode | str] = None,
    max_retries: int = 4,
):
    chat_id = message.chat.id
    lock = _get_lock(chat_id)
    async with lock:
        return await _with_retry(
            message.reply_text,
            text,
            parse_mode=parse_mode,
            max_retries=max_retries,
        )


async def reply_document_safe(
    message: Message,
    *,
    document: Any,
    max_retries: int = 4,
    **kwargs,
):
    chat_id = message.chat.id
    lock = _get_lock(chat_id)
    async with lock:
        return await _with_retry(
            message.reply_document,
            document=document,
            max_retries=max_retries,
            **kwargs,
        )


async def reply_audio_safe(
    message: Message,
    *,
    audio: Any,
    max_retries: int = 4,
    **kwargs,
):
    chat_id = message.chat.id
    lock = _get_lock(chat_id)
    async with lock:
        return await _with_retry(
            message.reply_audio,
            audio=audio,
            max_retries=max_retries,
            **kwargs,
        )
