"""Middleware to ensure bot only works in groups and whitelisted chats"""
from telegram import Update, Chat
from telegram.ext import ContextTypes
from utils.logger import setup_logger
from config.settings import GROUP_ONLY
from utils.whitelist import is_whitelisted

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
    user = update.effective_user
    
    # Allow only groups and supergroups
    is_group = chat.type in [Chat.GROUP, Chat.SUPERGROUP]
    
    if not is_group:
        user_id = user.id if user else "unknown"
        logger.warning(
            f"Blocked private chat attempt from user {user_id}"
        )
        # Send message to user explaining bot only works in groups
        if update.message:
            await update.message.reply_text(
                "⚠️ This bot only works in groups!\n\n"
                "Please add the bot to your Telegram group to use its features."
            )
        return False
    
    # Enforce whitelist for groups
    if not await is_whitelisted(chat.id):
        if update.message:
            await update.message.reply_text(
                "contact @hansobored for permission using bot"
            )
        logger.warning("Blocked non-whitelisted group %s", chat.id)
        return False

    logger.debug(f"Message from whitelisted group: {chat.id} ({chat.title})")
    return True
