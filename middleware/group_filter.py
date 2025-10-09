"""Middleware to ensure bot only works in groups"""
from telegram import Update, Chat
from telegram.ext import ContextTypes
from utils.logger import setup_logger
from config.settings import GROUP_ONLY

logger = setup_logger(__name__)

async def group_only_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Filter to check if message is from a group.
    
    Args:
        update: Telegram update
        context: Bot context
        
    Returns:
        True if from group, False otherwise
    """
    if not GROUP_ONLY:
        return True
    
    if not update.effective_chat:
        return False
    
    chat = update.effective_chat
    
    # Allow only groups and supergroups
    is_group = chat.type in [Chat.GROUP, Chat.SUPERGROUP]
    
    if not is_group:
        logger.warning(
            f"Blocked private chat attempt from user {update.effective_user.id}"
        )
        # Send message to user explaining bot only works in groups
        if update.message:
            await update.message.reply_text(
                "⚠️ Bot ini hanya bekerja di grup!\n\n"
                "Silakan tambahkan bot ke grup Telegram Anda untuk menggunakan fitur-fiturnya."
            )
        return False
    
    logger.debug(f"Message from group: {chat.id} ({chat.title})")
    return True
