#!/usr/bin/env bash
set -euo pipefail

# Start script: sets up env, installs deps, configures systemd, and runs the bot 24/7

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
UNIT_NAME="telegram-dev-bot.service"
UNIT_FILE="/etc/systemd/system/$UNIT_NAME"
FFMPEG_FLAG_FILE="$PROJECT_DIR/.installed.ffmpeg"

echo "[+] Project dir: $PROJECT_DIR"

# Basic checks
command -v python3 >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }
command -v pip3 >/dev/null 2>&1 || { echo "pip3 not found"; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "systemd (systemctl) not found. Please use a system with systemd."; exit 1; }

# Ensure .env exists (required by config/settings.py)
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "[!] Missing .env file at $PROJECT_DIR/.env"
  echo "    Create it with TELEGRAM_TOKEN and BYTEZ_API_KEY before running."
  exit 1
fi

# Create venv if missing
if [[ ! -d "$VENV_DIR" ]]; then
  echo "[+] Creating virtualenv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

echo "[+] Installing Python dependencies"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

# Ensure ffmpeg available via OS package manager
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[!] ffmpeg not found, attempting to install via package manager (sudo required)"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y ffmpeg
    touch "$FFMPEG_FLAG_FILE"
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y ffmpeg
    touch "$FFMPEG_FLAG_FILE"
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y epel-release || true
    sudo yum install -y ffmpeg
    touch "$FFMPEG_FLAG_FILE"
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm ffmpeg
    touch "$FFMPEG_FLAG_FILE"
  else
    echo "[!] Could not detect supported package manager. Please install ffmpeg manually."
  fi
fi

# Create systemd service unit
CURRENT_USER="$(id -un)"
PYTHON_BIN="$VENV_DIR/bin/python"

echo "[+] Creating systemd unit at $UNIT_FILE (sudo required)"
SERVICE_CONTENT="[Unit]
Description=Telegram Dev Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$PROJECT_DIR/.env
ExecStart=$PYTHON_BIN $PROJECT_DIR/bot.py
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"

echo "$SERVICE_CONTENT" | sudo tee "$UNIT_FILE" >/dev/null

echo "[+] Reloading systemd daemon"
sudo systemctl daemon-reload

echo "[+] Enabling and starting service: $UNIT_NAME"
sudo systemctl enable --now "$UNIT_NAME"

echo "[+] Service status (short):"
sudo systemctl --no-pager --full status "$UNIT_NAME" || true

echo "[✓] Bot installed and started via systemd. It will run 24/7 and auto-restart on failure."
echo "    Logs: journalctl -u $UNIT_NAME -f"
