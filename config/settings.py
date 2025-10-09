"""Configuration settings for the bot"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is required in .env file")

# AI Service Configuration
BYTEZ_API_KEY = os.getenv("BYTEZ_API_KEY")
if not BYTEZ_API_KEY:
    raise ValueError("BYTEZ_API_KEY is required in .env file")

BYTEZ_API_URL = "https://api.bytez.com/models/v2/Qwen/Qwen3-4B"
BYTEZ_TIMEOUT = 300.0  # 5 minutes

BYTEZ_IMAGE_MODEL_URL = "https://api.bytez.com/models/v2/stabilityai/stable-diffusion-xl-base-1.0"
BYTEZ_IMAGE_TIMEOUT = 300.0

# AI Model Parameters
AI_MAX_LENGTH = 2048
AI_TEMPERATURE = 0.7
AI_SYSTEM_PROMPT = (
    "You are a helpful assistant for developers in a Telegram group. "
    "Keep your answers concise and clear. "
    "IMPORTANT: Always format your response using Telegram's MarkdownV2 syntax. "
    "Use *text* for bold, and for code blocks, use triple backticks on their own separate lines, specifying the language."
)

# Flask Health Check Server
FLASK_PORT = int(os.getenv("PORT", 8080))
FLASK_HOST = "0.0.0.0"

# Rate Limiting (per user)
RATE_LIMIT_MESSAGES = 10  # messages
RATE_LIMIT_WINDOW = 60  # seconds

# File Download Configuration
TEMP_DIR = "/tmp"
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
DOWNLOAD_TIMEOUT = 24 * 60 * 60  # 24 hours

# Telegram upload timeout
TELEGRAM_UPLOAD_TIMEOUT = 24 * 60 * 60  # 24 hours

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Group Only Configuration
GROUP_ONLY = True  # Bot hanya bekerja di group
