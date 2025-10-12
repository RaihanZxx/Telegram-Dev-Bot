"""Message handlers for chat interactions"""
import re
from typing import List, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TelegramError
from middleware.group_filter import group_only_filter
from middleware.context_manager import context_manager
from services.ai_service import ai_service
from utils.rate_limiter import rate_limiter
from utils.markdown import format_telegram_markdown, clean_ai_response
from utils.logger import setup_logger
from utils.telegram_safe import (
    edit_message_text_safe,
    reply_text_safe,
)
from utils.challenge_manager import challenge_manager

logger = setup_logger(__name__)

MAX_MESSAGE_LENGTH = 4000
GREETING_KEYWORDS = {
    "hi",
    "hello",
    "halo",
    "hai",
    "hey",
    "test",
    "ping",
    "hallo"
}

def _normalize_message(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip().strip("!.?")


def _chunk_text(text: str, limit: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """Split text into chunks that fit within Telegram limits."""
    if not text:
        return []

    chunks: List[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_pos = remaining.rfind("\n", 0, limit)
        if split_pos == -1 or split_pos < int(limit * 0.5):
            split_pos = remaining.rfind(" ", 0, limit)
        if split_pos == -1 or split_pos < int(limit * 0.5):
            split_pos = limit

        chunk = remaining[:split_pos].rstrip()
        if chunk:
            chunks.append(chunk)

        remaining = remaining[split_pos:].lstrip()

    return chunks if chunks else [text[:limit]]


async def _deliver_long_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    thinking_message_id: int,
    message,
    chunks: List[str]
):
    """Deliver long responses by splitting into multiple messages."""
    if not chunks:
        return

    async def _send_chunk(
        chunk_text: str,
        *,
        edit_message_id: Optional[int] = None,
        reply_target=None
    ):
        formatted_chunk = format_telegram_markdown(chunk_text)
        try:
            if edit_message_id is not None:
                await edit_message_text_safe(
                    context.bot,
                    chat_id,
                    edit_message_id,
                    formatted_chunk,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            elif reply_target is not None:
                await reply_text_safe(
                    reply_target,
                    formatted_chunk,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
        except BadRequest as chunk_markdown_error:
            logger.warning(
                "Chunk markdown failed, sending plain text: %s",
                chunk_markdown_error
            )
            safe_text = chunk_text[:MAX_MESSAGE_LENGTH]
            try:
                if edit_message_id is not None:
                    await edit_message_text_safe(
                        context.bot,
                        chat_id,
                        edit_message_id,
                        safe_text,
                        parse_mode=None,
                    )
                elif reply_target is not None:
                    await reply_text_safe(reply_target, safe_text)
            except BadRequest as chunk_plain_error:
                logger.error(
                    "Plain text chunk delivery failed: %s",
                    chunk_plain_error
                )
                truncated = safe_text[:MAX_MESSAGE_LENGTH]
                if edit_message_id is not None:
                    await edit_message_text_safe(
                        context.bot,
                        chat_id,
                        edit_message_id,
                        truncated,
                        parse_mode=None,
                    )
                elif reply_target is not None:
                    await reply_text_safe(reply_target, truncated)
        except TelegramError as chunk_delivery_error:
            logger.error(
                "Telegram error while sending chunk: %s",
                chunk_delivery_error
            )
            truncated = chunk_text[:MAX_MESSAGE_LENGTH]
            if edit_message_id is not None:
                await edit_message_text_safe(
                    context.bot,
                    chat_id,
                    edit_message_id,
                    truncated,
                    parse_mode=None,
                )
            elif reply_target is not None:
                await reply_text_safe(reply_target, truncated)

    # Replace thinking message with first chunk
    await _send_chunk(
        chunks[0],
        edit_message_id=thinking_message_id
    )

    # Send remaining chunks as new messages
    for chunk in chunks[1:]:
        await _send_chunk(chunk, reply_target=message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming text messages.
    Bot responds when:
    - Mentioned (@botname)
    - Replied to
    - Direct message in group
    """
    # Check if in group
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    user = update.effective_user

    if message is None or chat is None or user is None:
        logger.warning("Message handler received incomplete update context")
        return

    if message.text is None:
        return

    bot_username = context.bot.username

    should_respond = False
    if message.reply_to_message and message.reply_to_message.from_user:
        should_respond = message.reply_to_message.from_user.id == context.bot.id

    if not should_respond and bot_username:
        should_respond = f"@{bot_username}" in message.text
    
    if not should_respond:
        return

    user_id = user.id
    group_id = chat.id
    user_message = message.text

    # If this is a reply to a pending challenge, handle evaluation path first
    if message.reply_to_message:
        pending = challenge_manager.get_pending(message.reply_to_message.message_id)
        if pending is not None:
            # Rate limit check
            allowed, wait_time = rate_limiter.is_allowed(user_id)
            if not allowed:
                await message.reply_text(f"⏳ You sent messages too quickly. Try again in {wait_time} second(s).")
                return

            thinking = await reply_text_safe(message, "🧪 Evaluating your answer…")

            eval_prompt = (
                "You are an automatic judge. Evaluate the following answer for a {diff}-level {lang} challenge.\n\n"
                "[CHALLENGE]\n{challenge}\n\n[SUBMISSION]\n{answer}\n\n"
                "Return the first line exactly as either 'VERDICT: CORRECT' or 'VERDICT: INCORRECT'.\n"
                "Then provide a brief 1-paragraph explanation."
            ).format(lang=pending.language, diff=pending.difficulty, challenge=pending.prompt, answer=user_message)

            try:
                eval_resp = await ai_service.get_response(eval_prompt)
            except Exception as e:  # noqa: BLE001
                logger.error("Evaluation error: %s", e, exc_info=True)
                eval_resp = "VERDICT: INCORRECT\nEvaluation failed, please try again."

            verdict_line = (eval_resp or "").splitlines()[0].strip().upper()
            is_correct = "CORRECT" in verdict_line and "INCORRECT" not in verdict_line

            pts_wrong = {"easy": 12.5, "medium": 25.0, "hard": 50.0}.get(pending.difficulty, 0.0)
            pts_right = {"easy": 25.0, "medium": 50.0, "hard": 100.0}.get(pending.difficulty, 0.0)
            awarded = pts_right if is_correct else pts_wrong
            total = challenge_manager.add_points(group_id, user_id, awarded)

            # Build leaderboard text
            top = challenge_manager.leaderboard(group_id, limit=10)
            lb_lines = []
            rank = 1
            for uid, score in top:
                label = f"ID {uid}"
                if uid == user_id and (user.username or user.first_name):
                    label = f"@{user.username}" if user.username else user.first_name
                lb_lines.append(f"{rank}. {label} — {score:.1f} pts")
                rank += 1
            leaderboard_text = "\n".join(lb_lines) if lb_lines else "(no entries yet)"

            result_text = (
                f"{eval_resp}\n\n"
                f"Points: +{awarded:.1f} (total {total:.1f})\n\n"
                f"🏆 /challenge Leaderboard:\n{leaderboard_text}"
            )

            formatted = format_telegram_markdown(result_text)
            await edit_message_text_safe(
                context.bot,
                chat.id,
                thinking.message_id,
                formatted,
                parse_mode=ParseMode.MARKDOWN_V2,
            )

            # Do not remove pending so others can also attempt; comment next line to allow multiple entries
            # challenge_manager.remove_pending(message.reply_to_message.message_id)
            return
    
    # Remove bot mention from message
    if bot_username:
        user_message = user_message.replace(f"@{bot_username}", "").strip()
    
    # Check rate limit
    allowed, wait_time = rate_limiter.is_allowed(user_id)
    if not allowed:
        await message.reply_text(
            f"⏳ You sent the message too quickly. "
            f"Try again in {wait_time} second."
        )
        logger.warning(f"Rate limit hit for user {user_id} in group {group_id}")
        return
    
    # Send thinking indicator
    thinking_message = await reply_text_safe(message, "🤔 Think...")

    # Quick replies for simple greetings/tests
    normalized_user_message = _normalize_message(user_message)
    if (
        normalized_user_message
        and " " not in normalized_user_message
        and normalized_user_message in GREETING_KEYWORDS
    ):
        quick_response = "Hello! How can I help you??"
        formatted_quick_response = format_telegram_markdown(quick_response)
        await edit_message_text_safe(
            context.bot,
            chat.id,
            thinking_message.message_id,
            formatted_quick_response,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        context_manager.add_message(group_id, "user", user_message)
        context_manager.add_message(group_id, "assistant", quick_response)
        return
    
    try:
        # Get conversation context
        conversation_history = context_manager.get_context(group_id)
        
        logger.info(
            f"Processing message from user {user_id} in group {group_id}, "
            f"history: {len(conversation_history)} messages"
        )
        
        # Get AI response
        ai_response = await ai_service.get_response(
            user_message,
            conversation_history
        )
        
        # Clean AI response (remove thinking tags)
        cleaned_response = clean_ai_response(ai_response)
        
        # Format markdown
        formatted_response = format_telegram_markdown(cleaned_response)
        
        # Send response
        try:
            try:
                await edit_message_text_safe(
                    context.bot,
                    chat.id,
                    thinking_message.message_id,
                    formatted_response,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except BadRequest as markdown_error:
                logger.warning(
                    "Markdown parsing failed, attempting fallback: %s",
                    markdown_error
                )

                error_text = str(markdown_error).lower()
                if "message is too long" in error_text or "message_too_long" in error_text:
                    try:
                        chunks = _chunk_text(cleaned_response)
                        await _deliver_long_message(
                            context,
                            chat.id,
                            thinking_message.message_id,
                            message,
                            chunks
                        )
                    except TelegramError as chunk_error:
                        logger.error(
                            "Failed to deliver chunked response: %s",
                            chunk_error
                        )
                        await message.reply_text(cleaned_response[:MAX_MESSAGE_LENGTH])
                else:
                    try:
                        await edit_message_text_safe(
                            context.bot,
                            chat.id,
                            thinking_message.message_id,
                            cleaned_response,
                            parse_mode=None,
                        )
                    except BadRequest as fallback_error:
                        logger.error(
                            "Fallback plain text delivery failed: %s",
                            fallback_error
                        )
                        await reply_text_safe(message, cleaned_response)
        except TelegramError as delivery_error:
            logger.error(
                "Failed to deliver response message: %s",
                delivery_error
            )
            await reply_text_safe(message, cleaned_response[:MAX_MESSAGE_LENGTH])
        
        # Update conversation context
        context_manager.add_message(group_id, "user", user_message)
        context_manager.add_message(group_id, "assistant", cleaned_response)
        
        logger.info(f"Successfully responded in group {group_id}")
        
    except Exception as e:
        logger.error(f"Error in message handler: {e}", exc_info=True)
        
        # Try to send error message
        try:
            await edit_message_text_safe(
                context.bot,
                chat.id,
                thinking_message.message_id,
                "❌ Sorry, there was a technical problem. Please try again later.",
            )
        except Exception as edit_error:
            logger.error(f"Failed to edit error message: {edit_error}")
            # Fallback: send new message
            await reply_text_safe(
                message,
                "❌ Sorry, there was a technical problem. Please try again later.",
            )
