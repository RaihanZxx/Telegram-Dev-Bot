"""Command handlers for the bot"""
import asyncio
import os
import time
from math import log2
from typing import Optional

from telegram import Update
from telegram.error import TimedOut, TelegramError, NetworkError
from config.settings import TELEGRAM_UPLOAD_TIMEOUT
from telegram.ext import ContextTypes
from middleware.group_filter import group_only_filter
from middleware.context_manager import context_manager
from services.file_service import file_service
from services.image_service import image_service
from utils.logger import setup_logger
from utils.upload_progress import UploadProgressReader
from utils.telegram_safe import (
    reply_text_safe,
    edit_text_safe,
    reply_document_safe,
    reply_audio_safe,
)
from utils.whitelist import add_group, is_whitelisted

logger = setup_logger(__name__)


def _format_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    if n <= 0:
        return "0 B"
    idx = min(int(log2(n) / 10), len(units) - 1)
    return f"{n / (1 << (10 * idx)):.2f} {units[idx]}"


def _format_eta(seconds: Optional[float]) -> str:
    if not seconds or seconds <= 0:
        return "--:--"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _progress_bar(percent: float, width: int = 20) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(round((percent / 100.0) * width))
    return f"[{'█' * filled}{'░' * (width - filled)}] {percent:5.1f}%"

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
        "👋 <b>Hello! I'm the Developer Assistant Bot</b>\n\n"
        "I am ready to help you with:\n"
        "• Answering coding questions\n"
        "• Debugging the problem\n"
        "• Explaining programming concepts\n"
        "• Download files with /mirror\n\n"
        "Use /help to see all available commands.."
    )
    
    await reply_text_safe(message, welcome_message, parse_mode="HTML")
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
        "📖 <b>Command List</b>\n\n"
        "<b>General:</b>\n"
        "/start - Show welcome message\n"
        "/help - Show this help\n"
        "/clear - Clear group conversation history\n\n"
        "<b>Admin:</b>\n"
        "/whitelist - Allow the bot to operate in this group (admin only).\n\n"
        "<b>File Management:</b>\n"
        "/mirror &lt;url&gt; - Download files from URL\n"
        "/music &lt;url&gt; - Download audio from YouTube link\n"
        "/clear_db - Clear temporary download files (alias: /clear-db)\n\n"
        "<b>AI Tools:</b>\n"
        "/image &lt;description&gt; - Generate image from text prompt\n\n"
        "<b>Tips:</b>\n"
        "• Mention the bot or reply to its message to ask questions\n"
        "• The bot keeps a 30-minute conversation memory\n"
        "• Maximum download size: 2 GB\n"
        "• Rate limit: 10 messages per minute per user\n"
        "• The bot only works in whitelisted groups; if not, contact @hansobored"
    )
    
    await reply_text_safe(message, help_message, parse_mode="HTML")
    logger.info(f"Help command from group {chat.id}")


ADMIN_ID = 6677851276


async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: whitelist current group so bot can operate here"""
    message = update.message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    if user.id != ADMIN_ID:
        await reply_text_safe(message, "❌ You are not allowed to use this command.")
        return

    if chat.type not in ("group", "supergroup"):
        await reply_text_safe(message, "⚠️ Use this command inside the target group.")
        return

    if await is_whitelisted(chat.id):
        await reply_text_safe(message, "✅ This group is already whitelisted.")
        return

    await add_group(chat.id)
    await reply_text_safe(message, f"✅ Group {chat.id} has been whitelisted. Bot is now enabled here.")


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
    
    await reply_text_safe(message, "🗑️ Conversation history has been deleted!")
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

    status_message = await reply_text_safe(message, "🧹 Cleaning temporary folders...")

    files_removed, dirs_removed, errors = await asyncio.to_thread(file_service.cleanup_temp_directory)

    parts = []
    if files_removed:
        parts.append(f"{files_removed} file")
    if dirs_removed:
        parts.append(f"{dirs_removed} folder")
    summary = ", ".join(parts) if parts else "There are no files to clean up."

    if errors:
        response = (
            "⚠️ Cleanup completed with some failures.\n"
            f"🧹 Cleaned: {summary}\n"
            f"❗️ Failed to delete: {errors} item."
        )
    else:
        response = (
            "✅ Folder sementara berhasil dibersihkan!\n"
            f"🧹 Dibersihkan: {summary}"
        )

    await edit_text_safe(status_message, response)
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
        await reply_text_safe(
            "❌ Please provide the file URL.\n"
            "Contoh: <code>/mirror https://example.com/file.zip</code>",
            parse_mode="HTML"
        )
        return
    
    url = context.args[0]
    status_message = await reply_text_safe(message, "🔗 Starting download...")

    async def _runner():
        local_file_path = None
        download_duration = None
        upload_duration = None
        upload_start = None
        try:
            filename = url.split('/')[-1].split('?')[0] or "file"
            await edit_text_safe(status_message, f"📥 Downloading `{filename}`...")

            async def _on_progress(downloaded: int, total: Optional[int], speed_bps: float):
                try:
                    if total and total > 0:
                        percent = (downloaded / total) * 100.0
                        bar = _progress_bar(percent)
                        text = (
                            f"📥 Downloading `{filename}`\n"
                            f"{bar}\n"
                            f"{_format_size(downloaded)} / { _format_size(total) }\n"
                            f"⚡ {_format_size(int(speed_bps))}/s | ⏳ {_format_eta((total - downloaded) / speed_bps if speed_bps else None)}"
                        )
                    else:
                        text = (
                            f"📥 Downloading `{filename}`\n"
                            f"{_format_size(downloaded)} downloaded\n"
                            f"⚡ {_format_size(int(speed_bps))}/s"
                        )
                    await edit_text_safe(status_message, text)
                except Exception:
                    pass

            download_start = time.monotonic()
            success, status_text, local_file_path = await file_service.download_file(url, progress_callback=_on_progress)
            download_duration = time.monotonic() - download_start

            if not success:
                extra = f"\n⏱️ Download: {download_duration:.2f}s" if download_duration is not None else ""
                await edit_text_safe(status_message, f"{status_text}{extra}")
                return

            if local_file_path is None:
                await edit_text_safe(status_message, "❌ File not available after download.")
                return

            await edit_text_safe(status_message, f"📤 Uploading `{filename}`...")

            file_size = os.path.getsize(local_file_path)
            base_f = open(local_file_path, 'rb')
            wrapped = UploadProgressReader(base_f, file_size)
            stop_event = asyncio.Event()

            async def _upload_progress_updater():
                last = 0.0
                while not stop_event.is_set():
                    try:
                        now = time.monotonic()
                        if now - last >= 1.0:
                            read = wrapped.bytes_read
                            percent = (read / file_size * 100.0) if file_size else 0.0
                            bar = _progress_bar(percent)
                            elapsed = max(0.001, now - wrapped.start_time)
                            speed = int(read / elapsed)
                            eta = (file_size - read) / speed if speed > 0 else None
                            text = (
                                f"📤 Uploading `{filename}`\n"
                                f"{bar}\n"
                                f"{_format_size(read)} / {_format_size(file_size)}\n"
                                f"⚡ {_format_size(speed)}/s | ⏳ {_format_eta(eta)}"
                            )
                            await status_message.edit_text(text)
                            last = now
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

            upload_start = time.monotonic()
            updater_task = asyncio.create_task(_upload_progress_updater())
            try:
                try:
                    await reply_document_safe(
                        message,
                        document=wrapped,
                        read_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                        write_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                    )
                except NetworkError as ne:
                    if "Request Entity Too Large" in str(ne):
                        logger.warning("Upload rejected with 413. Falling back to Telegram fetch-by-URL.")
                        try:
                            await edit_text_safe(
                                f"⚠️ Upload too large for direct send. Trying via URL fetch...\n📎 {filename}"
                            )
                        except Exception:
                            pass
                        await reply_document_safe(
                            message,
                            document=url,
                            read_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                            write_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                        )
                    else:
                        raise
            finally:
                stop_event.set()
                try:
                    await updater_task
                except Exception:
                    pass
                try:
                    base_f.close()
                except Exception:
                    pass
            upload_duration = time.monotonic() - upload_start

            success_text = (
                "✅ Finished!\n"
                f"📄 {filename}\n"
                f"⏱️ Download: {download_duration:.2f}s\n"
                f"📤 Upload: {upload_duration:.2f}s"
            )
            try:
                await edit_text_safe(status_message, success_text)
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
                extra_parts.append(f"📤 Upload: {upload_duration:.2f}s")
            extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
            try:
                await edit_text_safe(
                    "❌ An error occurred: Uploading to Telegram exceeded the time limit.."
                    " Please try again in a few moments." + extras
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
                extra_parts.append(f"📤 Upload: {upload_duration:.2f}s")
            extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
            try:
                await edit_text_safe(
                    "❌ An error occurred: Uploading to Telegram exceeded the time limit."
                    " Please try again in a few moments." + extras
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
                extra_parts.append(f"📤 Upload: {upload_duration:.2f}s")
            extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
            await edit_text_safe(status_message, f"❌ There is an error: {str(e)}{extras}")
        finally:
            if local_file_path:
                file_service.cleanup_file(local_file_path)

    context.application.create_task(_runner())
    return


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
        await reply_text_safe(
            "❌ Please provide the music URL.\n"
            "Example: <code>/music https://music.youtube.com/watch?v=hsfa1RSk0pA</code>",
            parse_mode="HTML"
        )
        return

    url = context.args[0]
    status_message = await reply_text_safe(message, "🎵 Processing music links...")

    async def _runner():
        local_file_path = None
        download_duration = None
        upload_duration = None
        metadata = None
        try:
            await edit_text_safe(status_message, "📥 Downloading audio...")

            async def _on_progress(downloaded: int, total: Optional[int], speed: Optional[float], eta: Optional[float]):
                try:
                    if total and total > 0:
                        percent = (downloaded / total) * 100.0
                        bar = _progress_bar(percent)
                        text = (
                            "🎵 Downloading audio...\n"
                            f"{bar}\n"
                            f"{_format_size(downloaded)} / { _format_size(total) }\n"
                            f"⚡ {_format_size(int(speed or 0))}/s | ⏳ {_format_eta(eta)}"
                        )
                    else:
                        text = (
                            "🎵 Downloading audio...\n"
                            f"{_format_size(downloaded)} downloaded\n"
                            f"⚡ {_format_size(int(speed or 0))}/s"
                        )
                    await edit_text_safe(status_message, text)
                except Exception:
                    pass

            download_start = time.monotonic()
            success, info_message, local_file_path, metadata = await file_service.download_audio(url, progress_callback=_on_progress)
            download_duration = time.monotonic() - download_start

            if not success:
                extra = f"\n⏱️ Download: {download_duration:.2f}s" if download_duration is not None else ""
                await edit_text_safe(status_message, f"{info_message}{extra}")
                return

            if local_file_path is None:
                await edit_text_safe(status_message, "❌ Audio file is not available after download.")
                return

            await edit_text_safe(status_message, "📤 Uploading audio...")

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

            file_size = os.path.getsize(local_file_path)
            base_f = open(local_file_path, 'rb')
            wrapped = UploadProgressReader(base_f, file_size)
            stop_event = asyncio.Event()

            async def _upload_progress_updater_audio():
                last = 0.0
                while not stop_event.is_set():
                    try:
                        now = time.monotonic()
                        if now - last >= 1.0:
                            read = wrapped.bytes_read
                            percent = (read / file_size * 100.0) if file_size else 0.0
                            bar = _progress_bar(percent)
                            elapsed = max(0.001, now - wrapped.start_time)
                            speed = int(read / elapsed)
                            eta = (file_size - read) / speed if speed > 0 else None
                            text = (
                                "📤 Uploading audio...\n"
                                f"{bar}\n"
                                f"{_format_size(read)} / {_format_size(file_size)}\n"
                                f"⚡ {_format_size(speed)}/s | ⏳ {_format_eta(eta)}"
                            )
                            await status_message.edit_text(text)
                            last = now
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

            upload_start = time.monotonic()
            updater_task = asyncio.create_task(_upload_progress_updater_audio())
            try:
                await reply_audio_safe(
                    message,
                    audio=wrapped,
                    read_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                    write_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                    **kwargs,
                )
            finally:
                stop_event.set()
                try:
                    await updater_task
                except Exception:
                    pass
                try:
                    base_f.close()
                except Exception:
                    pass
            upload_duration = time.monotonic() - upload_start

            display_name = title or local_file_path.split('/')[-1]
            await edit_text_safe(status_message,
                "✅ Music sent successfully!\n"
                f"🎶 {display_name}\n"
                f"⏱️ Download: {download_duration:.2f}s\n"
                f"📤 Upload: {upload_duration:.2f}s"
            )
            logger.info(f"Music command successful for {display_name} in group {chat.id}")

        except Exception as e:
            logger.error(f"Error in music command: {e}", exc_info=True)
            extra_parts = []
            if download_duration is not None:
                extra_parts.append(f"⏱️ Download: {download_duration:.2f}s")
            if upload_duration is not None:
                extra_parts.append(f"📤 Upload: {upload_duration:.2f}s")
            extras = f"\n{'\n'.join(extra_parts)}" if extra_parts else ""
            await edit_text_safe(status_message, f"❌ There is an error: {str(e)}{extras}")
        finally:
            if local_file_path:
                file_service.cleanup_file(local_file_path)

    context.application.create_task(_runner())
    return


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
        await reply_text_safe(
            "❌ Please provide a description of the image.\n"
            "Example: <code>/image kucing astronot</code>",
            parse_mode="HTML",
        )
        return

    status_message = await reply_text_safe(message, "🎨 Produces images...")

    try:
        image_buffer = await image_service.generate_image(prompt)
        if image_buffer is None:
            await edit_text_safe(status_message, "❌ Failed to create image. Please try again later.")
            return

        await message.reply_photo(photo=image_buffer, caption=f"🖼️ Prompt: {prompt}")
        await edit_text_safe(status_message, "✅ Image created successfully!")
        logger.info("Image generated for prompt in group %s", chat.id)

    except Exception as exc:  # noqa: BLE001
        logger.error("Error in image command: %s", exc, exc_info=True)
        await edit_text_safe(status_message, "❌ An error occurred while creating the image..")
