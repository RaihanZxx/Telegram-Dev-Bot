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
    send_document_safe,
    send_audio_safe,
    delete_message_safe,
)
from utils.whitelist import add_group, is_whitelisted
from utils.download_tracker import download_tracker
from utils.music_tracker import music_tracker

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
            "✅ Temporary folder cleaned successfully!\n"
            f"🧹 Cleaned: {summary}"
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
    user = update.effective_user
    if message is None or chat is None:
        logger.warning("Mirror command without message or chat context")
        return

    if not context.args:
        await reply_text_safe(
            message,
            "❌ Please provide the file URL.\n"
            "Example: <code>/mirror https://example.com/file.zip</code>",
            parse_mode="HTML"
        )
        return
    
    url = context.args[0]
    topic_id: Optional[int] = None
    # find optional topic id like -1724 among args
    for a in context.args[1:]:
        cleaned = a.rstrip(".,)")
        if cleaned.lstrip("-").isdigit():
            try:
                topic_id = abs(int(cleaned))
            except ValueError:
                topic_id = None
            break

    # Per-user concurrency limit (2)
    user_id = user.id if user else 0
    chat_id = chat.id
    if not download_tracker.can_start(chat_id, user_id):
        await reply_text_safe(message, "❌ Maximum concurrent downloads per user is 2. Finish active tasks first.")
        return

    # User/Group display strings
    user_display = (f"@{user.username}" if user and user.username else (user.first_name if user else str(user_id)))
    group_display = chat.title or str(chat_id)

    tracker = await download_tracker.ensure_tracker(chat_id, user_id, user_display, group_display)
    if tracker.message_id is None:
        # Create a unified status message for this user's tasks in this group
        banner = f"Task [{user_display}] Mirror.\nGroup [{group_display}]\nPreparing task…"
        banner_msg = await reply_text_safe(message, banner)
        await download_tracker.set_message_id(tracker, banner_msg.message_id)

    # Prepare initial filename & register task before scheduling
    temp_filename = url.split('/')[-1].split('?')[0] or "file"
    task_meta = download_tracker.start_task(tracker, temp_filename)
    # Initial render in minimalist format
    try:
        await download_tracker.update_task(
            context.bot,
            tracker,
            task_meta.id,
            stage="download",
            downloaded=0,
            total=None,
            speed_bps=0.0,
        )
    except Exception:
        pass

    async def _runner(task_id: str):
        local_file_path = None
        download_duration = None
        upload_duration = None
        upload_start = None
        try:
            task = type("T", (), {"id": task_id})

            async def _on_progress(downloaded: int, total: Optional[int], speed_bps: float):
                try:
                    await download_tracker.update_task(
                        context.bot,
                        tracker,
                        task.id,
                        stage="download",
                        downloaded=downloaded,
                        total=total,
                        speed_bps=speed_bps,
                    )
                except Exception:
                    pass

            download_start = time.monotonic()
            success, status_text, local_file_path = await file_service.download_file(url, progress_callback=_on_progress)
            download_duration = time.monotonic() - download_start

            if not success:
                await download_tracker.finish_task(context.bot, tracker, task.id, success=False)
                return

            if local_file_path is None:
                await download_tracker.finish_task(context.bot, tracker, task.id, success=False)
                return

            if not os.path.exists(local_file_path):
                await download_tracker.finish_task(context.bot, tracker, task.id, success=False)
                return

            file_size = os.path.getsize(local_file_path)
            # Get actual filename from downloaded file
            filename = os.path.basename(local_file_path)
            # Update task with real filename
            try:
                tracker.tasks[task_meta.id].filename = filename
            except Exception:
                pass
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
                            elapsed = max(0.001, now - wrapped.start_time)
                            speed = int(read / elapsed)
                            eta = (file_size - read) / speed if speed > 0 else None
                            _ = eta  # not used in minimalist view
                            await download_tracker.update_task(
                                context.bot,
                                tracker,
                                task.id,
                                stage="upload",
                                downloaded=read,
                                total=file_size,
                                speed_bps=float(speed),
                            )
                            last = now
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

            upload_start = time.monotonic()
            updater_task = asyncio.create_task(_upload_progress_updater())
            try:
                try:
                    send_kwargs = dict(
                        chat_id=chat_id,
                        document=wrapped,
                        read_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                        write_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                    )
                    if topic_id:
                        send_kwargs["message_thread_id"] = topic_id
                        logger.info(f"Uploading file: {filename} ({_format_size(file_size)}) to group {chat_id}, topic {topic_id}")
                    else:
                        logger.info(f"Uploading file: {filename} ({_format_size(file_size)}) to group {chat_id}")
                    await send_document_safe(
                        context.bot,
                        **send_kwargs,
                    )
                except NetworkError as ne:
                    if "Request Entity Too Large" in str(ne):
                        logger.warning("Upload rejected with 413. Falling back to Telegram fetch-by-URL.")
                        fallback_kwargs = dict(
                            chat_id=chat_id,
                            document=url,
                            read_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                            write_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                        )
                        if topic_id:
                            fallback_kwargs["message_thread_id"] = topic_id
                        await send_document_safe(
                            context.bot,
                            **fallback_kwargs,
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

            await download_tracker.finish_task(context.bot, tracker, task.id, success=True)

        except asyncio.CancelledError:
            # user-triggered cancellation
            try:
                await download_tracker.finish_task(context.bot, tracker, task_id, success=False)
            finally:
                raise

        except TimedOut as e:
            logger.error(f"Upload timed out for mirror command: {e}", exc_info=True)
            if upload_start is not None:
                upload_duration = time.monotonic() - upload_start
            await download_tracker.finish_task(context.bot, tracker, task.id, success=False)
            return
        except asyncio.TimeoutError as e:
            logger.error(f"Async operation timed out for mirror command: {e}", exc_info=True)
            if upload_start is not None:
                upload_duration = time.monotonic() - upload_start
            await download_tracker.finish_task(context.bot, tracker, task.id, success=False)
            return
        except Exception as e:
            logger.error(f"Error in mirror command: {e}", exc_info=True)
            await download_tracker.finish_task(context.bot, tracker, task.id, success=False)
        finally:
            if local_file_path:
                file_service.cleanup_file(local_file_path)

    handle = context.application.create_task(_runner(task_meta.id))
    download_tracker.bind_handle(tracker, task_meta.id, handle)
    # Auto-delete the command message to keep chat clean
    try:
        await delete_message_safe(message)
    except Exception:
        pass
    return


async def cancel_dl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel all active download/upload tasks for the requesting user in this group."""
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    chat_id = chat.id
    user_id = user.id
    user_display = (f"@{user.username}" if user.username else user.first_name)
    group_display = chat.title or str(chat_id)

    tracker = await download_tracker.ensure_tracker(chat_id, user_id, user_display, group_display)
    active = [t for t in tracker.tasks.values() if t.stage not in ("done", "error")]
    if not active:
        await reply_text_safe(message, "ℹ️ No active download tasks to cancel.")
        # Delete the command message to keep chat clean
        try:
            await delete_message_safe(message)
        except Exception:
            pass
        return

    await download_tracker.cancel_all(context.bot, tracker)
    await reply_text_safe(message, "🛑 Your download tasks have been cancelled.")
    # Delete the command message to keep chat clean
    try:
        await delete_message_safe(message)
    except Exception:
        pass


async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /music command - download audio with unified minimal status like mirror"""
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    user = update.effective_user
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
    # Optional topic id like -1724 to post audio into specific thread
    topic_id: Optional[int] = None
    def _extract_topic(args_list) -> Optional[int]:
        import re
        for tok in args_list[1:]:
            cleaned = tok.strip().strip(".,)]}(")
            cleaned = cleaned.replace("–", "-").replace("—", "-").replace("−", "-")
            if cleaned.startswith("#"):
                cleaned = cleaned[1:]
            m = re.fullmatch(r"-?(\d{1,10})", cleaned)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue
        return None
    topic_id = _extract_topic(context.args)

    # Unified per-user status banner like mirror
    chat_id = chat.id
    user_id = user.id if user else 0
    user_display = (f"@{user.username}" if user and user.username else (user.first_name if user else str(user_id)))
    group_display = chat.title or str(chat_id)
    tracker = await music_tracker.ensure_tracker(chat_id, user_id, user_display, group_display)
    if tracker.message_id is None:
        banner = f"🎵 <b>Task</b> [{user_display}] <b>Music</b>\n👥 <b>Group</b> [{group_display}]\nPreparing task…"
        banner_msg = await reply_text_safe(message, banner, parse_mode="HTML")
        await music_tracker.set_message_id(tracker, banner_msg.message_id)

    # Pre-register a task; later we'll update filename if title is found
    provisional_name = url.split('/')[-1].split('?')[0] or "audio"
    task_meta = music_tracker.start_task(tracker, provisional_name)
    try:
        await music_tracker.update_task(context.bot, tracker, task_meta.id, stage="download", downloaded=0, total=None, speed_bps=0.0)
    except Exception:
        pass

    async def _runner():
        local_file_path = None
        upload_start = None
        metadata = None
        try:
            async def _on_progress(downloaded: int, total: Optional[int], speed: Optional[float], eta: Optional[float]):
                try:
                    await music_tracker.update_task(
                        context.bot,
                        tracker,
                        task_meta.id,
                        stage="download",
                        downloaded=downloaded,
                        total=total,
                        speed_bps=float(speed or 0.0),
                    )
                except Exception:
                    pass

            success, info_message, local_file_path, metadata = await file_service.download_audio(url, progress_callback=_on_progress)
            if not success or not local_file_path:
                await music_tracker.finish_task(context.bot, tracker, task_meta.id, success=False)
                return

            kwargs = {}
            title = metadata.get("title") if metadata else None
            if title:
                kwargs["title"] = title
                try:
                    tracker.tasks[task_meta.id].filename = title
                except Exception:
                    pass
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
                            elapsed = max(0.001, now - wrapped.start_time)
                            speed = int(read / elapsed)
                            await music_tracker.update_task(
                                context.bot,
                                tracker,
                                task_meta.id,
                                stage="upload",
                                downloaded=read,
                                total=file_size,
                                speed_bps=float(speed),
                            )
                            last = now
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

            upload_start = time.monotonic()
            updater_task = asyncio.create_task(_upload_progress_updater_audio())
            try:
                send_kwargs = dict(
                    chat_id=chat.id,
                    audio=wrapped,
                    read_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                    write_timeout=TELEGRAM_UPLOAD_TIMEOUT,
                    **kwargs,
                )
                if topic_id:
                    send_kwargs["message_thread_id"] = topic_id
                await send_audio_safe(
                    context.bot,
                    **send_kwargs,
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

            await music_tracker.finish_task(context.bot, tracker, task_meta.id, success=True)
            logger.info("Music command successful in group %s", chat.id)

        except Exception as e:
            logger.error(f"Error in music command: {e}", exc_info=True)
            await music_tracker.finish_task(context.bot, tracker, task_meta.id, success=False)
        finally:
            if local_file_path:
                file_service.cleanup_file(local_file_path)

    context.application.create_task(_runner())
    # Auto-delete the command message to keep chat clean
    try:
        await delete_message_safe(message)
    except Exception:
        pass
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
            "Example: <code>/image astronaut cat</code>",
            parse_mode="HTML",
        )
        return

    status_message = await reply_text_safe(message, "🎨 Generating images...")

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
