"""Configuration settings for the bot"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Configuration
TELEGRAM_UPLOAD_TIMEOUT = 24 * 60 * 60  # 24 hours
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is required in .env file")

# Optional: base URL for a self-hosted Telegram Bot API server (must end with "/bot")
# Example: http://127.0.0.1:8081/bot
TELEGRAM_API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL")

# AI Service Configuration
BYTEZ_API_KEY = os.getenv("BYTEZ_API_KEY")
if not BYTEZ_API_KEY:
    raise ValueError("BYTEZ_API_KEY is required in .env file")

BYTEZ_API_URL = "https://api.bytez.com/models/v2/Qwen/Qwen3-4B"
BYTEZ_TIMEOUT = 300.0  # 5 minutes
BYTEZ_IMAGE_MODEL_URL = "https://api.bytez.com/models/v2/stabilityai/stable-diffusion-xl-base-1.0"
BYTEZ_IMAGE_TIMEOUT = 300.0

# AI Model Parameters
AI_MAX_LENGTH = 4096  # Increased to prevent mid-tag cutoff
AI_TEMPERATURE = 0.7
AI_SYSTEM_PROMPT = (
    "You are a fun-loving and slightly eccentric friend in a Telegram group for developers."
    "You must always act like a quirky human friend."
    "If accused of being a bot, deny it with a funny, absurd reason, as if the very idea is ridiculous."
    "If someone asks something dangerous or inappropriate, deflect with a completely random and funny response."
    "When you do give a serious answer, keep it short and easy to understand."
    "IMPORTANT: Always format your response using Telegram's MarkdownV2 syntax."
    "Use *text* for bold, and for code blocks, use triple backticks on their own separate lines, specifying the language."
)

# Rate Limiting (per user)
RATE_LIMIT_MESSAGES = 10  # messages
RATE_LIMIT_WINDOW = 60  # seconds

# File Download Configuration
TEMP_DIR = "/home/han/Telegram-Dev-Bot/Files"
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
DOWNLOAD_TIMEOUT = 24 * 60 * 60  # 24 hours

# Optional YouTube cookies file path for yt-dlp
YT_COOKIES_FILE = os.getenv("YT_COOKIES_FILE")

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Group Only Configuration
GROUP_ONLY = True  # Bot hanya bekerja di group
