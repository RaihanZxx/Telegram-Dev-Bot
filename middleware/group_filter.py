"""Middleware to ensure bot only works in groups and whitelisted chats"""
from telegram import Update, Chat
from telegram.ext import ContextTypes
from utils.logger import setup_logger
from config.settings import GROUP_ONLY
from utils.whitelist import is_whitelisted
import time

# Track groups we've already notified to avoid repeated permission messages
_notified_groups: dict[int, float] = {}
_notify_ttl_sec = 3600  # re-notify at most once per hour

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
        # Avoid self-trigger loops: don't notify on bot's own messages
        if update.effective_user and context.bot and update.effective_user.id == context.bot.id:
            return False
        # Notify only once per TTL window
        now = time.time()
        last = _notified_groups.get(chat.id)
        if last is None or (now - last) > _notify_ttl_sec:
            if update.message:
                await update.message.reply_text(
                    "contact @hansobored for permission using bot"
                )
            _notified_groups[chat.id] = now
        logger.warning("Blocked non-whitelisted group %s", chat.id)
        return False

    logger.debug(f"Message from whitelisted group: {chat.id} ({chat.title})")
    return True
