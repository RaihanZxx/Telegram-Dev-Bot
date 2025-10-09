"""Command handlers for the bot"""
import asyncio
import time

from telegram import Update
from telegram.error import TimedOut, TelegramError
from config.settings import TELEGRAM_UPLOAD_TIMEOUT
from telegram.ext import ContextTypes
from middleware.group_filter import group_only_filter
from middleware.context_manager import context_manager
from services.file_service import file_service
from services.image_service import image_service
from utils.logger import setup_logger

logger = setup_logger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        logger.warning("Start command without message or chat context")
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
    
    await message.reply_text(
        welcome_message,
        parse_mode="HTML"
    )
    logger.info(f"Start command from group {chat.id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    if not await group_only_filter(update, context):
        return
    
    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        logger.warning("Help command without message or chat context")
        return

    help_message = (
        "📖 <b>Daftar Command</b>\n\n"
        "<b>Umum:</b>\n"
        "/start - Tampilkan pesan selamat datang\n"
        "/help - Tampilkan bantuan ini\n"
        "/clear - Hapus history percakapan grup\n\n"
        "<b>File Management:</b>\n"
        "/mirror &lt;url&gt; - Download file dari URL\n"
        "/music &lt;url&gt; - Download audio dari tautan YouTube\n"
        "/clear_db - Bersihkan file sementara download (alias: /clear-db)\n\n"
        "<b>AI Tools:</b>\n"
        "/image &lt;deskripsi&gt; - Generate gambar dari prompt teks\n\n"
        "<b>Tips:</b>\n"
        "• Mention bot atau reply pesannya untuk bertanya\n"
        "• Bot memiliki memori percakapan selama 30 menit\n"
        "• Maximum file size untuk download: 2 GB\n"
        "• Rate limit: 10 pesan per menit per user"
    )
    
    await message.reply_text(
        help_message,
        parse_mode="HTML"
    )
    logger.info(f"Help command from group {chat.id}")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command - clear conversation context"""
    if not await group_only_filter(update, context):
        return
    
    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        logger.warning("Clear command without message or chat context")
        return

    group_id = chat.id
    context_manager.clear_context(group_id)
    
    await message.reply_text(
        "🗑️ History percakapan telah dihapus!"
    )
    logger.info(f"Clear command from group {group_id}")


async def clear_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear_db command - cleanup temp files"""
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        logger.warning("Clear DB command without message or chat context")
        return

    status_message = await message.reply_text("🧹 Membersihkan folder sementara...")

    files_removed, dirs_removed, errors = await asyncio.to_thread(file_service.cleanup_temp_directory)

    parts = []
    if files_removed:
        parts.append(f"{files_removed} file")
    if dirs_removed:
        parts.append(f"{dirs_removed} folder")
    summary = ", ".join(parts) if parts else "Tidak ada berkas yang perlu dibersihkan"

    if errors:
        response = (
            "⚠️ Pembersihan selesai dengan beberapa kegagalan.\n"
            f"🧹 Dibersihkan: {summary}\n"
            f"❗️ Gagal dihapus: {errors} item."
        )
    else:
        response = (
            "✅ Folder sementara berhasil dibersihkan!\n"
            f"🧹 Dibersihkan: {summary}"
        )

    await status_message.edit_text(response)
    logger.info(
        "Clear DB command executed in group %s (files: %s, dirs: %s, errors: %s)",
        chat.id,
        files_removed,
        dirs_removed,
        errors,
    )


async def mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mirror command - download files"""
    if not await group_only_filter(update, context):
        return
    
    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        logger.warning("Mirror command without message or chat context")
        return

    if not context.args:
        await message.reply_text(
            "❌ Tolong berikan URL file.\n"
            "Contoh: <code>/mirror https://example.com/file.zip</code>",
            parse_mode="HTML"
        )
        return
    
    url = context.args[0]
    status_message = await message.reply_text("🔗 Memulai download...")
    local_file_path = None
    download_duration = None
    upload_duration = None
    upload_start = None
    
    try:
        # Extract filename for display
        filename = url.split('/')[-1].split('?')[0] or "file"
        
        await status_message.edit_text(f"📥 Mengunduh `{filename}`...")
        
        # Download file
        download_start = time.monotonic()
        success, status_text, local_file_path = await file_service.download_file(url)
        download_duration = time.monotonic() - download_start
        
        if not success:
            extra = f"\n⏱️ Download: {download_duration:.2f}s" if download_duration is not None else ""
            await status_message.edit_text(f"{status_text}{extra}")
            return
        
        if local_file_path is None:
            await status_message.edit_text("❌ File tidak tersedia setelah diunduh.")
            return
        
        # Upload to Telegram
        await status_message.edit_text(f"📤 Mengunggah `{filename}`...")
        
        upload_start = time.monotonic()
        with open(local_file_path, 'rb') as f:
            await message.reply_document(
                document=f,
                read_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                write_timeout=TELEGRAM_UPLOAD_TIMEOUT
            )
        upload_duration = time.monotonic() - upload_start
        
        success_text = (
            "✅ Selesai!\n"
            f"📄 {filename}\n"
            f"⏱️ Download: {download_duration:.2f}s\n"
            f"📤 Unggah: {upload_duration:.2f}s"
        )
        try:
            await status_message.edit_text(success_text)
        except (TimedOut, asyncio.TimeoutError) as edit_error:
            logger.warning(f"Status message update timed out: {edit_error}")
        except TelegramError as edit_error:
            logger.warning(f"Status message update failed: {edit_error}")
        logger.info(f"Mirror successful for {filename} in group {chat.id}")
        
    except TimedOut as e:
        logger.error(f"Upload timed out for mirror command: {e}", exc_info=True)
        if upload_start is not None:
            upload_duration = time.monotonic() - upload_start
        extra_parts = []
        if download_duration is not None:
            extra_parts.append(f"⏱️ Download: {download_duration:.2f}s")
        if upload_duration is not None:
            extra_parts.append(f"📤 Unggah: {upload_duration:.2f}s")
        extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
        try:
            await status_message.edit_text(
                "❌ Terjadi kesalahan: Pengunggahan ke Telegram melebihi batas waktu."
                " Mohon coba lagi dalam beberapa saat." + extras
            )
        except (TimedOut, asyncio.TimeoutError) as edit_error:
            logger.warning(f"Status message update timed out after upload timeout: {edit_error}")
        except TelegramError as edit_error:
            logger.warning(f"Status message update failed after upload timeout: {edit_error}")
        return
    except asyncio.TimeoutError as e:
        logger.error(f"Async operation timed out for mirror command: {e}", exc_info=True)
        if upload_start is not None:
            upload_duration = time.monotonic() - upload_start
        extra_parts = []
        if download_duration is not None:
            extra_parts.append(f"⏱️ Download: {download_duration:.2f}s")
        if upload_duration is not None:
            extra_parts.append(f"📤 Unggah: {upload_duration:.2f}s")
        extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
        try:
            await status_message.edit_text(
                "❌ Terjadi kesalahan: Pengunggahan ke Telegram melebihi batas waktu."
                " Mohon coba lagi dalam beberapa saat." + extras
            )
        except (TimedOut, asyncio.TimeoutError) as edit_error:
            logger.warning(f"Status message update timed out after async timeout: {edit_error}")
        except TelegramError as edit_error:
            logger.warning(f"Status message update failed after async timeout: {edit_error}")
        return
        
    except Exception as e:
        logger.error(f"Error in mirror command: {e}", exc_info=True)
        extra_parts = []
        if download_duration is not None:
            extra_parts.append(f"⏱️ Download: {download_duration:.2f}s")
        if upload_duration is not None:
            extra_parts.append(f"📤 Unggah: {upload_duration:.2f}s")
        extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
        await status_message.edit_text(f"❌ Terjadi kesalahan: {str(e)}{extras}")
    
    finally:
        # Cleanup
        if local_file_path:
            file_service.cleanup_file(local_file_path)


async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /music command - download audio"""
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        logger.warning("Music command without message or chat context")
        return

    if not context.args:
        await message.reply_text(
            "❌ Tolong berikan URL musik.\n"
            "Contoh: <code>/music https://music.youtube.com/watch?v=hsfa1RSk0pA</code>",
            parse_mode="HTML"
        )
        return

    url = context.args[0]
    status_message = await message.reply_text("🎵 Memproses tautan musik...")
    local_file_path = None
    download_duration = None
    upload_duration = None
    metadata = None

    try:
        await status_message.edit_text("📥 Mengunduh audio...")

        download_start = time.monotonic()
        success, info_message, local_file_path, metadata = await file_service.download_audio(url)
        download_duration = time.monotonic() - download_start

        if not success:
            extra = f"\n⏱️ Download: {download_duration:.2f}s" if download_duration is not None else ""
            await status_message.edit_text(f"{info_message}{extra}")
            return
        
        if local_file_path is None:
            await status_message.edit_text("❌ File audio tidak tersedia setelah diunduh.")
            return

        await status_message.edit_text("📤 Mengunggah audio...")

        kwargs = {}
        title = metadata.get("title") if metadata else None
        if title:
            kwargs["title"] = title
        duration_value = metadata.get("duration") if metadata else None
        if duration_value:
            try:
                kwargs["duration"] = int(float(duration_value))
            except (TypeError, ValueError):
                pass

        upload_start = time.monotonic()
        with open(local_file_path, 'rb') as f:
            await message.reply_audio(audio=f, **kwargs)
        upload_duration = time.monotonic() - upload_start

        display_name = title or local_file_path.split('/')[-1]
        await status_message.edit_text(
            "✅ Musik berhasil dikirim!\n"
            f"🎶 {display_name}\n"
            f"⏱️ Download: {download_duration:.2f}s\n"
            f"📤 Unggah: {upload_duration:.2f}s"
        )
        logger.info(f"Music command successful for {display_name} in group {chat.id}")

    except Exception as e:
        logger.error(f"Error in music command: {e}", exc_info=True)
        extra_parts = []
        if download_duration is not None:
            extra_parts.append(f"⏱️ Download: {download_duration:.2f}s")
        if upload_duration is not None:
            extra_parts.append(f"📤 Unggah: {upload_duration:.2f}s")
        extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
        await status_message.edit_text(f"❌ Terjadi kesalahan: {str(e)}{extras}")

    finally:
        if local_file_path:
            file_service.cleanup_file(local_file_path)


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /image command - generate images"""
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    if message is None or chat is None:
        logger.warning("Image command without message or chat context")
        return

    prompt_parts = context.args or []
    prompt = " ".join(prompt_parts).strip()

    if not prompt and message.reply_to_message and message.reply_to_message.text:
        prompt = message.reply_to_message.text.strip()

    if not prompt:
        await message.reply_text(
            "❌ Tolong berikan deskripsi gambar.\n"
            "Contoh: <code>/image kucing astronot</code>",
            parse_mode="HTML",
        )
        return

    status_message = await message.reply_text("🎨 Menghasilkan gambar...")

    try:
        image_buffer = await image_service.generate_image(prompt)
        if image_buffer is None:
            await status_message.edit_text("❌ Gagal membuat gambar. Coba lagi nanti.")
            return

        await message.reply_photo(photo=image_buffer, caption=f"🖼️ Prompt: {prompt}")
        await status_message.edit_text("✅ Gambar berhasil dibuat!")
        logger.info("Image generated for prompt in group %s", chat.id)

    except Exception as exc:  # noqa: BLE001
        logger.error("Error in image command: %s", exc, exc_info=True)
        await status_message.edit_text("❌ Terjadi kesalahan saat membuat gambar.")
