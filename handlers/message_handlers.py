"""Message handlers for chat interactions"""
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from middleware.group_filter import group_only_filter
from middleware.context_manager import context_manager
from services.ai_service import ai_service
from utils.rate_limiter import rate_limiter
from utils.markdown import format_telegram_markdown, clean_ai_response
from utils.logger import setup_logger

logger = setup_logger(__name__)

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
    
    # Remove bot mention from message
    if bot_username:
        user_message = user_message.replace(f"@{bot_username}", "").strip()
    
    # Check rate limit
    allowed, wait_time = rate_limiter.is_allowed(user_id)
    if not allowed:
        await message.reply_text(
            f"⏳ Anda mengirim pesan terlalu cepat. "
            f"Coba lagi dalam {wait_time} detik."
        )
        logger.warning(f"Rate limit hit for user {user_id} in group {group_id}")
        return
    
    # Send thinking indicator
    thinking_message = await message.reply_text("🤔 Berpikir...")
    
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
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=thinking_message.message_id,
            text=formatted_response,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        # Update conversation context
        context_manager.add_message(group_id, "user", user_message)
        context_manager.add_message(group_id, "assistant", cleaned_response)
        
        logger.info(f"Successfully responded in group {group_id}")
        
    except Exception as e:
        logger.error(f"Error in message handler: {e}", exc_info=True)
        
        # Try to send error message
        try:
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=thinking_message.message_id,
                text="❌ Maaf, terjadi gangguan teknis. Coba lagi nanti."
            )
        except Exception as edit_error:
            logger.error(f"Failed to edit error message: {edit_error}")
            # Fallback: send new message
            await message.reply_text(
                "❌ Maaf, terjadi gangguan teknis. Coba lagi nanti."
            )
