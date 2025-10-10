"""Markdown formatting utilities for Telegram MarkdownV2"""
import re
import uuid
from typing import Match
from telegram.helpers import escape_markdown
from utils.logger import setup_logger

logger = setup_logger(__name__)


def _store_segment(store: dict, prefix: str, value: str) -> str:
    """Create a unique placeholder and store the original value."""
    placeholder = f"{prefix}PLACEHOLDER{uuid.uuid4().hex}"
    store[placeholder] = value
    return placeholder


def format_telegram_markdown(text: str) -> str:
    """
    Convert generic markdown to Telegram MarkdownV2 format.
    Handles code blocks and escapes special characters while preserving
    bold and italic formatting.
    
    Args:
        text: Raw text with markdown formatting
        
    Returns:
        Telegram MarkdownV2 compatible text
    """
    try:
        # Convert markdown headings (with space) to bold before processing
        text = re.sub(r'^\s*#+\s+(.+)$', r'**\1**', text, flags=re.MULTILINE)

        code_blocks: dict[str, str] = {}
        inline_code_blocks: dict[str, str] = {}
        bold_segments: dict[str, str] = {}
        italic_segments: dict[str, str] = {}

        # Extract code blocks (```code```)
        text_processed = re.sub(
            r"```.*?```",
            lambda match: _store_segment(code_blocks, "CODE", match.group(0)),
            text,
            flags=re.DOTALL,
        )

        # Extract inline code (`code`)
        text_processed = re.sub(
            r"`[^`]+`",
            lambda match: _store_segment(inline_code_blocks, "INLINE", match.group(0)),
            text_processed,
        )

        # Extract bold segments (**text** or __text__)
        bold_pattern = re.compile(r"(\*\*|__)(.+?)\1", re.DOTALL)
        text_processed = bold_pattern.sub(
            lambda match: _store_segment(bold_segments, "BOLD", match.group(2)),
            text_processed,
        )

        # Extract italic segments (*text* or _text_)
        italic_star_pattern = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)")
        italic_underscore_pattern = re.compile(r"(?<!_)_(?!_)([^_\n]+?)(?<!_)_(?!_)")
        text_processed = italic_star_pattern.sub(
            lambda match: _store_segment(italic_segments, "ITALIC", match.group(1)),
            text_processed,
        )
        text_processed = italic_underscore_pattern.sub(
            lambda match: _store_segment(italic_segments, "ITALIC", match.group(1)),
            text_processed,
        )

        # Escape remaining special characters for MarkdownV2
        escaped_text = escape_markdown(text_processed, version=2)

        # Restore bold and italic segments with proper escaping
        for placeholder, content in bold_segments.items():
            escaped_content = escape_markdown(content, version=2)
            escaped_text = escaped_text.replace(placeholder, f"*{escaped_content}*")

        for placeholder, content in italic_segments.items():
            escaped_content = escape_markdown(content, version=2)
            escaped_text = escaped_text.replace(placeholder, f"_{escaped_content}_")

        # Restore inline code and code blocks
        for placeholder, original_block in inline_code_blocks.items():
            escaped_text = escaped_text.replace(placeholder, original_block)

        for placeholder, original_block in code_blocks.items():
            escaped_text = escaped_text.replace(placeholder, original_block)

        # Ensure opening code fences start on a new line
        escaped_text = re.sub(r'(?<!\n)```', r'\n```', escaped_text)
        escaped_text = re.sub(r'```(?!\n)', r'```\n', escaped_text)

        return escaped_text

    except Exception as e:
        logger.error(f"Error formatting markdown: {e}", exc_info=True)
        # Fallback: return plain text without markdown
        return text.replace('*', '').replace('_', '').replace('`', '')


def clean_ai_response(text: str) -> str:
    """
    Clean AI response by removing thinking tags and extra whitespace.
    
    Args:
        text: Raw AI response
        
    Returns:
        Cleaned text
    """
    # Remove thinking tags (for models that expose reasoning)
    # Handle both normal </think> and escaped </\think> from AI models
    text = re.sub(r'<think>.*?</\\?think>\s*', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Trim at known code-insertion markers
    for marker in (
        "<|fim_middle|>",
        "<|fim_suffix|>",
        "<|fim_prefix|>",
        "<|fimprefix|>",
        "<|filesep|>",
        "<|file_sep|>",
    ):
        if marker in text:
            text = text.split(marker, 1)[0]

    # Remove duplicate language identifiers inside code blocks
    def _strip_redundant_lang(match: Match[str]) -> str:
        language = match.group(1)
        content = match.group(2)
        lines = content.splitlines()

        # Remove leading empty lines
        idx = 0
        while idx < len(lines) and lines[idx].strip() == "":
            idx += 1

        # Remove first non-empty line if it repeats the language identifier
        if idx < len(lines) and lines[idx].strip().lower() == language.lower():
            del lines[idx]

        rebuilt = '\n'.join(lines)

        if content.endswith('\n') and not rebuilt.endswith('\n'):
            rebuilt += '\n'

        return f"```{language}\n{rebuilt}```"

    text = re.sub(r"```([a-zA-Z0-9_+-]+)\n([\s\S]*?)```", _strip_redundant_lang, text)

    # Remove excessive whitespace
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)

    return text.strip()
