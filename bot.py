#!/usr/bin/env python3
"""
Telegram Developer Assistant Bot
A professional bot for helping developers in Telegram groups.
"""
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config.settings import TELEGRAM_TOKEN, TELEGRAM_API_BASE_URL
from handlers.command_handlers import (
    start_command,
    help_command,
    clear_command,
    clear_db_command,
    mirror_command,
    cancel_dl_command,
    music_command,
    image_command,
    whitelist_command,
)
from handlers.message_handlers import handle_message
from handlers.challenge_handlers import (
    challenge_command,
    challenge_lang_callback,
    challenge_diff_callback,
    ranking_command,
)
from utils.logger import setup_logger

logger = setup_logger(__name__)

def main():
    """Main entry point"""
    logger.info("Starting Telegram Developer Assistant Bot...")

    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment")
        return

    builder = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True)
    if TELEGRAM_API_BASE_URL:
        builder = builder.base_url(TELEGRAM_API_BASE_URL)
    application = builder.build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("clear_db", clear_db_command))
    application.add_handler(MessageHandler(filters.Regex(r"^/clear-db(?:@\w+)?$"), clear_db_command))
    application.add_handler(CommandHandler("mirror", mirror_command))
    application.add_handler(CommandHandler("cancel_dl", cancel_dl_command))
    application.add_handler(MessageHandler(filters.Regex(r"^/cancel-dl(?:@\w+)?$"), cancel_dl_command))
    application.add_handler(CommandHandler("music", music_command))
    application.add_handler(CommandHandler("image", image_command))
    application.add_handler(CommandHandler("whitelist", whitelist_command))
    application.add_handler(CommandHandler("challenge", challenge_command))
    application.add_handler(CommandHandler("rangking", ranking_command))
    application.add_handler(CommandHandler("ranking", ranking_command))
    application.add_handler(CallbackQueryHandler(challenge_lang_callback, pattern=r"^challenge_lang:"))
    application.add_handler(CallbackQueryHandler(challenge_diff_callback, pattern=r"^challenge_diff:"))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot handlers registered")
    logger.info("Bot is now polling for updates...")

    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
