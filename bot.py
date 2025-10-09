#!/usr/bin/env python3
"""
Telegram Developer Assistant Bot
A professional bot for helping developers in Telegram groups.
"""
import threading
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config.settings import TELEGRAM_TOKEN, FLASK_HOST, FLASK_PORT
from handlers.command_handlers import (
    start_command,
    help_command,
    clear_command,
    mirror_command
)
from handlers.message_handlers import handle_message
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Flask health check server
app = Flask(__name__)

@app.route('/')
def health_check():
    """Health check endpoint"""
    return {"status": "ok", "message": "Bot is running"}, 200

@app.route('/health')
def health():
    """Alternative health check endpoint"""
    return {"status": "healthy"}, 200

def run_flask():
    """Run Flask server in background"""
    logger.info(f"Starting Flask server on {FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)

def main():
    """Main entry point"""
    logger.info("Starting Telegram Developer Assistant Bot...")
    
    # Validate configuration
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment")
        return
    
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask health check server started")
    
    # Build application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("mirror", mirror_command))
    
    # Register message handler (for chat)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    
    logger.info("Bot handlers registered")
    logger.info("Bot is now polling for updates...")
    
    # Start bot
    application.run_polling(
        allowed_updates=["message"],
        drop_pending_updates=True
    )

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
