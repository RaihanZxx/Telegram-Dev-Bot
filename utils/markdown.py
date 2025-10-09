"""Markdown formatting utilities for Telegram MarkdownV2"""
import re
import uuid
from utils.logger import setup_logger

logger = setup_logger(__name__)

def format_telegram_markdown(text: str) -> str:
    """
    Convert generic markdown to Telegram MarkdownV2 format.
    Handles code blocks and escapes special characters.
    
    Args:
        text: Raw text with markdown formatting
        
    Returns:
        Telegram MarkdownV2 compatible text
    """
    try:
        code_blocks = {}
        
        # Extract code blocks to protect them from escaping
        def replace_with_placeholder(match):
            placeholder = f"PLACEHOLDER{uuid.uuid4().hex}END"
            code_blocks[placeholder] = match.group(0)
            return placeholder
        
        text_no_code = re.sub(r'```.*?```', replace_with_placeholder, text, flags=re.DOTALL)
        
        # Escape special characters (except in code blocks)
        escape_chars = r'\_*[]()~`>#+=-|{}.!'
        text_escaped = re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text_no_code)
        
        # Convert markdown headings to bold
        text_formatted = re.sub(r'^\s*#+\s*(.*)', r'*\1*', text_escaped, flags=re.MULTILINE)
        
        # Convert **bold** to *bold*
        text_formatted = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text_formatted)
        
        # Restore code blocks
        final_text = text_formatted
        for placeholder, original_block in code_blocks.items():
            final_text = final_text.replace(placeholder, original_block)
        
        # Ensure code blocks are on separate lines
        final_text = re.sub(r'(?<!\n)```', r'\n```', final_text)
        final_text = re.sub(r'```(?!\n)', r'```\n', final_text)
        
        return final_text
    
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
    text = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove excessive whitespace
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    
    return text.strip()
