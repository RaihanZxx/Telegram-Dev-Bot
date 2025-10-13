#!/usr/bin/env bash
# ensure bash when invoked via sh
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

# Interactive setup: infra (swap, firewall, Docker, Bot API, Nginx+TLS) + bot venv + systemd

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
UNIT_NAME="telegram-dev-bot.service"
UNIT_FILE="/etc/systemd/system/$UNIT_NAME"
FFMPEG_FLAG_FILE="$PROJECT_DIR/.installed.ffmpeg"

echo "[+] Project dir: $PROJECT_DIR"

command -v systemctl >/dev/null 2>&1 || { echo "systemd (systemctl) not found"; exit 1; }

pkg_install() {
  local pkgs=("$@")
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y "${pkgs[@]}"
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y "${pkgs[@]}"
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y "${pkgs[@]}"
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm "${pkgs[@]}"
  else
    return 1
  fi
}

# ensure curl for later steps
if ! command -v curl >/dev/null 2>&1; then
  echo "[+] Installing curl"
  pkg_install curl || true
fi

ensure_python() {
  local need=0
  command -v python3 >/dev/null 2>&1 || need=1
  command -v pip3 >/dev/null 2>&1 || need=1
  if [ "$need" -eq 1 ]; then
    echo "[+] Installing python3, pip, venv"
    if command -v apt-get >/dev/null 2>&1; then
      pkg_install python3 python3-pip python3-venv
    elif command -v dnf >/dev/null 2>&1; then
      pkg_install python3 python3-pip
    elif command -v yum >/dev/null 2>&1; then
      pkg_install python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
      pkg_install python python-pip
    fi
  fi
  command -v python3 >/dev/null 2>&1 || { echo "python3 not found after install"; exit 1; }
  command -v pip3 >/dev/null 2>&1 || { echo "pip3 not found after install"; exit 1; }
}

ensure_python

ask_yes_no() { local p="$1"; read -r -p "$p [y/N]: " ans || true; [[ "${ans:-}" =~ ^[Yy]$ ]]; }
prompt() { local p="$1"; local v; read -r -p "$p: " v; echo "$v"; }

echo "[1] Prep: IP, swap, firewall"
PUB_IP=$(curl -s https://ifconfig.me || true)
echo "    Public IP: ${PUB_IP:-unknown}"
if ask_yes_no "    Create 2G swap now"; then
  if ! sudo swapon --show | grep -q "/swapfile"; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  else
    echo "    Swapfile already active"
  fi
fi
if ask_yes_no "    Setup UFW and allow 80,443"; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y ufw
  fi
  sudo ufw allow 80,443/tcp || true
  sudo ufw allow OpenSSH || true
  sudo ufw enable || true
  sudo ufw status || true
fi

echo "[2] Install Docker"
if ! command -v docker >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo $UBUNTU_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io
    sudo systemctl enable --now docker
  else
    echo "    Docker install skipped (unsupported distro). Install manually."
  fi
else
  echo "    Docker already installed"
fi

echo "[3] Run telegram-bot-api on localhost:8081"
if ask_yes_no "    Configure and (re)run Bot API container"; then
  TELEGRAM_API_ID=${TELEGRAM_API_ID:-}
  TELEGRAM_API_HASH=${TELEGRAM_API_HASH:-}
  [[ -n "$TELEGRAM_API_ID" ]] || TELEGRAM_API_ID=$(prompt "    Enter TELEGRAM_API_ID")
  [[ -n "$TELEGRAM_API_HASH" ]] || TELEGRAM_API_HASH=$(prompt "    Enter TELEGRAM_API_HASH")
  sudo mkdir -p /var/lib/telegram-bot-api /opt/tgbotapi
  sudo tee /opt/tgbotapi/.env >/dev/null <<EOF
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
EOF
  sudo docker rm -f tgbotapi >/dev/null 2>&1 || true
  sudo docker pull aiogram/telegram-bot-api:latest
  sudo docker run -d --name tgbotapi --restart unless-stopped \
    -p 127.0.0.1:8081:8081 \
    --env-file /opt/tgbotapi/.env \
    -v /var/lib/telegram-bot-api:/var/lib/telegram-bot-api \
    aiogram/telegram-bot-api:latest \
    --local --http-port=8081 --dir=/var/lib/telegram-bot-api
fi

echo "[4] Install and configure Nginx + TLS"
DOMAIN=${DOMAIN:-}
[[ -n "$DOMAIN" ]] || DOMAIN=$(prompt "    Enter domain (e.g. bot.example.com)")
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y nginx certbot python3-certbot-nginx
fi
sudo tee /etc/nginx/sites-available/telegram-bot-api.conf >/dev/null <<EOF
server {
  listen 80;
  server_name $DOMAIN;
  client_max_body_size 2048M;
  proxy_read_timeout 3600s;
  proxy_send_timeout 3600s;
  location /bot {
    proxy_pass http://127.0.0.1:8081/bot;
    proxy_http_version 1.1;
    proxy_buffering off;
  }
  location = /healthz { return 200 "ok\n"; add_header Content-Type text/plain; }
}
EOF
sudo ln -sf /etc/nginx/sites-available/telegram-bot-api.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
if ask_yes_no "    Issue HTTPS certificate via certbot for $DOMAIN"; then
  sudo certbot --nginx -d "$DOMAIN" --redirect || true
fi

echo "[5] Set bot to use your server"
BASE_URL="https://$DOMAIN/bot"
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "[!] .env not found. Creating minimal .env"
  TELEGRAM_TOKEN_VAL=$(prompt "    Enter TELEGRAM_TOKEN (from BotFather)")
  BYTEZ_API_KEY_VAL=$(prompt "    Enter BYTEZ_API_KEY")
  tee "$PROJECT_DIR/.env" >/dev/null <<EOF
TELEGRAM_TOKEN=$TELEGRAM_TOKEN_VAL
BYTEZ_API_KEY=$BYTEZ_API_KEY_VAL
TELEGRAM_API_BASE_URL=$BASE_URL
EOF
else
  if grep -q '^TELEGRAM_API_BASE_URL=' "$PROJECT_DIR/.env"; then
    sed -i "s#^TELEGRAM_API_BASE_URL=.*#TELEGRAM_API_BASE_URL=$BASE_URL#g" "$PROJECT_DIR/.env"
  else
    echo "TELEGRAM_API_BASE_URL=$BASE_URL" >> "$PROJECT_DIR/.env"
  fi
fi

# Python env & deps
if [[ ! -d "$VENV_DIR" ]]; then
  echo "[+] Creating virtualenv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
echo "[+] Installing Python dependencies"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

# ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[!] ffmpeg not found, installing"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y ffmpeg
    touch "$FFMPEG_FLAG_FILE"
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y ffmpeg && touch "$FFMPEG_FLAG_FILE"
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y epel-release || true
    sudo yum install -y ffmpeg && touch "$FFMPEG_FLAG_FILE"
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm ffmpeg && touch "$FFMPEG_FLAG_FILE"
  fi
fi

# systemd unit
CURRENT_USER="$(id -un)"
PYTHON_BIN="$VENV_DIR/bin/python"
echo "[+] Creating systemd unit (sudo)"
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
sudo systemctl daemon-reload
sudo systemctl enable --now "$UNIT_NAME"
sudo systemctl --no-pager --full status "$UNIT_NAME" || true
echo "[✓] Setup complete. Logs: journalctl -u $UNIT_NAME -f"
