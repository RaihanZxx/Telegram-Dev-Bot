"""Command handlers for the bot"""
from telegram import Update
from telegram.ext import ContextTypes
from middleware.group_filter import group_only_filter
from middleware.context_manager import context_manager
from services.file_service import file_service
from utils.logger import setup_logger

logger = setup_logger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if not await group_only_filter(update, context):
        return
    
    welcome_message = (
        "👋 <b>Halo! Saya Bot Asisten Developer</b>\n\n"
        "Saya siap membantu Anda dengan:\n"
        "• Menjawab pertanyaan coding\n"
        "• Debugging masalah\n"
        "• Menjelaskan konsep pemrograman\n"
        "• Download file dengan /mirror\n\n"
        "Gunakan /help untuk melihat semua command yang tersedia."
    )
    
    await update.message.reply_text(
        welcome_message,
        parse_mode="HTML"
    )
    logger.info(f"Start command from group {update.effective_chat.id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    if not await group_only_filter(update, context):
        return
    
    help_message = (
        "📖 <b>Daftar Command</b>\n\n"
        "<b>Umum:</b>\n"
        "/start - Tampilkan pesan selamat datang\n"
        "/help - Tampilkan bantuan ini\n"
        "/clear - Hapus history percakapan grup\n\n"
        "<b>File Management:</b>\n"
        "/mirror &lt;url&gt; - Download file dari URL\n\n"
        "<b>Tips:</b>\n"
        "• Mention bot atau reply pesannya untuk bertanya\n"
        "• Bot memiliki memori percakapan selama 30 menit\n"
        "• Maximum file size untuk download: 50 MB\n"
        "• Rate limit: 10 pesan per menit per user"
    )
    
    await update.message.reply_text(
        help_message,
        parse_mode="HTML"
    )
    logger.info(f"Help command from group {update.effective_chat.id}")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command - clear conversation context"""
    if not await group_only_filter(update, context):
        return
    
    group_id = update.effective_chat.id
    context_manager.clear_context(group_id)
    
    await update.message.reply_text(
        "🗑️ History percakapan telah dihapus!"
    )
    logger.info(f"Clear command from group {group_id}")


async def mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mirror command - download files"""
    if not await group_only_filter(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Tolong berikan URL file.\n"
            "Contoh: <code>/mirror https://example.com/file.zip</code>",
            parse_mode="HTML"
        )
        return
    
    url = context.args[0]
    status_message = await update.message.reply_text("🔗 Memulai download...")
    
    try:
        # Extract filename for display
        filename = url.split('/')[-1].split('?')[0] or "file"
        
        await status_message.edit_text(f"📥 Mengunduh `{filename}`...")
        
        # Download file
        success, message, local_file_path = await file_service.download_file(url)
        
        if not success:
            await status_message.edit_text(message)
            return
        
        # Upload to Telegram
        await status_message.edit_text(f"📤 Mengunggah `{filename}`...")
        
        with open(local_file_path, 'rb') as f:
            await update.message.reply_document(document=f)
        
        await status_message.delete()
        logger.info(f"Mirror successful for {filename} in group {update.effective_chat.id}")
        
    except Exception as e:
        logger.error(f"Error in mirror command: {e}", exc_info=True)
        await status_message.edit_text(f"❌ Terjadi kesalahan: {str(e)}")
    
    finally:
        # Cleanup
        if local_file_path:
            file_service.cleanup_file(local_file_path)
