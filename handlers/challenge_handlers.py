"""Handlers for /challenge feature with language and difficulty selection"""
from __future__ import annotations

from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from middleware.group_filter import group_only_filter
from services.ai_service import ai_service
from utils.challenge_manager import challenge_manager, PendingChallenge
from utils.markdown import format_telegram_markdown
from utils.telegram_safe import reply_text_safe, edit_text_safe
from utils.logger import setup_logger

logger = setup_logger(__name__)


LANGUAGES = [
    ("Python", "python"),
    ("Rust", "rust"),
    ("C++", "cpp"),
]

DIFFICULTIES = [
    ("Easy", "easy"),
    ("Medium", "medium"),
    ("Hard", "hard"),
]


async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: ask user to choose programming language"""
    if not await group_only_filter(update, context):
        return

    message = update.message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    kb = [
        [InlineKeyboardButton(text=label, callback_data=f"challenge_lang:{value}")]
        for label, value in LANGUAGES
    ]
    markup = InlineKeyboardMarkup(kb)

    await reply_text_safe(
        message,
        "Choose a programming language for the challenge:",
        reply_markup=markup,
    )


async def challenge_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection; prompt difficulty"""
    q = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    if not q or not chat or not user:
        return

    data = q.data or ""
    if not data.startswith("challenge_lang:"):
        return
    lang = data.split(":", 1)[1]

    challenge_manager.set_language(chat.id, user.id, lang)

    kb = [
        [InlineKeyboardButton(text=label, callback_data=f"challenge_diff:{lang}:{value}")]
        for label, value in DIFFICULTIES
    ]
    markup = InlineKeyboardMarkup(kb)
    try:
        await edit_text_safe(q.message, f"Language selected: {lang}.\nChoose difficulty:", reply_markup=markup)
    except Exception:
        await reply_text_safe(q.message, f"Language selected: {lang}.\nChoose difficulty:", reply_markup=markup)
    await q.answer()


async def challenge_diff_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle difficulty selection; generate a challenge and post it"""
    q = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    if not q or not chat or not user:
        return

    data = q.data or ""
    if not data.startswith("challenge_diff:"):
        return
    try:
        _, lang, diff = data.split(":", 2)
    except ValueError:
        # Fallback to stored language
        lang = challenge_manager.get_language(chat.id, user.id) or "python"
        diff = "easy"

    await q.answer()

    # Acknowledge selection and generate challenge
    try:
        await edit_text_safe(q.message, f"Language: {lang}\nDifficulty: {diff}\nGenerating challenge…")
    except Exception:
        pass

    gen_prompt = (
        "Create a {diff}-level programming challenge in {lang}. "
        "Provide a clear problem statement, success criteria, and 1-2 input/output examples. "
        "Do NOT include the solution. Keep it concise and tidy."
    ).format(lang=lang, diff=diff)

    try:
        content = await ai_service.get_response(gen_prompt)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to get challenge from AI: %s", e, exc_info=True)
        content = "❌ Failed to generate a challenge. Please try again later."

    # Inform user to reply to this message with the answer
    tail = (
        "\n\nReply to this message with your answer/solution. "
        "The bot will evaluate your submission."
    )
    challenge_text = f"{content}{tail}"

    formatted = format_telegram_markdown(challenge_text)
    sent = await reply_text_safe(q.message, formatted, parse_mode="MarkdownV2")

    challenge_manager.clear_selection(chat.id, user.id)
    challenge_manager.add_pending(
        sent.message_id,
        PendingChallenge(
            chat_id=chat.id,
            user_id=user.id,
            language=lang,
            difficulty=diff,
            prompt=content,
        ),
    )
