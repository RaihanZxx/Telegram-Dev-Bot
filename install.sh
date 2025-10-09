#!/bin/bash

# Skrip instalasi untuk Telegram Dev Bot

echo "Memulai instalasi Telegram Dev Bot..."

# Mengecek apakah Python3 terinstal
if ! command -v python3 &> /dev/null; then
    echo "Python3 tidak ditemukan! Silakan instal Python3 terlebih dahulu."
    exit 1
fi

# Mengecek apakah pip terinstal
if ! command -v pip3 &> /dev/null; then
    echo "pip3 tidak ditemukan! Silakan instal pip3 terlebih dahulu."
    exit 1
fi

# Membuat virtual environment jika belum ada
if [ ! -d "venv" ]; then
    echo "Membuat virtual environment..."
    python3 -m venv venv
fi

# Mengaktifkan virtual environment
source venv/bin/activate

# Menginstal dependensi dari requirements.txt
echo "Menginstal dependensi..."
pip3 install -r requirements.txt

echo "Instalasi selesai! Untuk menjalankan bot, gunakan perintah:"
echo "1. Aktifkan virtual environment: source venv/bin/activate"
echo "2. Jalankan bot: python bot.py"