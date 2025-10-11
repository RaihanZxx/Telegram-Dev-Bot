#!/usr/bin/env bash
set -euo pipefail

# Uninstall script: stops and removes systemd unit, removes venv, and optionally removes ffmpeg if we installed it

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT_NAME="telegram-dev-bot.service"
UNIT_FILE="/etc/systemd/system/$UNIT_NAME"
VENV_DIR="$PROJECT_DIR/venv"
FFMPEG_FLAG_FILE="$PROJECT_DIR/.installed.ffmpeg"

echo "[+] Uninstalling Telegram Dev Bot from $PROJECT_DIR"

if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-enabled --quiet "$UNIT_NAME" 2>/dev/null; then
    echo "[+] Disabling service"
    sudo systemctl disable "$UNIT_NAME" || true
  fi
  if systemctl is-active --quiet "$UNIT_NAME" 2>/dev/null; then
    echo "[+] Stopping service"
    sudo systemctl stop "$UNIT_NAME" || true
  fi
  if [[ -f "$UNIT_FILE" ]]; then
    echo "[+] Removing unit file"
    sudo rm -f "$UNIT_FILE"
    echo "[+] Reloading systemd daemon"
    sudo systemctl daemon-reload
  fi
else
  echo "[!] systemd not found; skipping service removal"
fi

# Remove venv
if [[ -d "$VENV_DIR" ]]; then
  echo "[+] Removing virtualenv at $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

# Optionally uninstall ffmpeg if installed by start.sh
if [[ -f "$FFMPEG_FLAG_FILE" ]]; then
  echo "[!] Detected ffmpeg was installed by start.sh; attempting removal (sudo required)"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get remove -y ffmpeg || true
    sudo apt-get autoremove -y || true
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf remove -y ffmpeg || true
  elif command -v yum >/dev/null 2>&1; then
    sudo yum remove -y ffmpeg || true
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Rns --noconfirm ffmpeg || true
  fi
  rm -f "$FFMPEG_FLAG_FILE"
fi

echo "[✓] Uninstall complete."
