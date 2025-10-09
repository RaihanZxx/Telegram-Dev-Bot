# Telegram Developer Assistant Bot 🤖

Bot asisten developer profesional untuk grup Telegram dengan fitur AI dan manajemen file.

## ✨ Fitur

- 🤖 **AI Assistant**: Menjawab pertanyaan coding menggunakan Bytez AI (Qwen3-4B)
- 💬 **Context Memory**: Mengingat percakapan hingga 30 menit
- 📥 **File Mirror**: Download dan upload file ke Telegram (max 50MB)
- 🛡️ **Rate Limiting**: Anti-spam (10 pesan/menit per user)
- 👥 **Group Only**: Hanya bekerja di grup Telegram
- 📊 **Professional Logging**: Structured logging untuk monitoring
- 🔄 **Conversation History**: Mempertahankan konteks percakapan

## 📁 Struktur Project

```
telegram-dev-bot/
├── bot.py                          # Main entry point
├── config/
│   └── settings.py                 # Konfigurasi aplikasi
├── services/
│   ├── ai_service.py              # AI integration
│   └── file_service.py            # File operations
├── handlers/
│   ├── command_handlers.py        # Command handlers
│   └── message_handlers.py        # Message handlers
├── utils/
│   ├── logger.py                  # Logging system
│   ├── markdown.py                # Markdown formatter
│   └── rate_limiter.py            # Rate limiting
└── middleware/
    ├── group_filter.py            # Group-only filter
    └── context_manager.py         # Conversation context
```

## 🚀 Instalasi

1. Clone repository
```bash
cd Telegram-Dev-Bot
```

2. Buat virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Setup environment variables
```bash
cp .env.example .env
# Edit .env dan isi:
# - TELEGRAM_TOKEN (dari @BotFather)
# - BYTEZ_API_KEY (dari https://bytez.com/api)
```

5. Jalankan bot
```bash
python bot.py
```

## 📝 Commands

- `/start` - Pesan selamat datang
- `/help` - Daftar semua command
- `/clear` - Hapus history percakapan grup
- `/mirror <url>` - Download file dari URL

## 💬 Cara Menggunakan

Bot akan merespon ketika:
- Di-mention: `@botname pertanyaan`
- Di-reply: Reply ke pesan bot
- Dalam grup: Otomatis detect mention

## ⚙️ Konfigurasi

Edit `config/settings.py` untuk mengatur:
- AI model dan parameters
- Rate limiting
- File size limits
- Timeout values
- Log level

## 🔒 Security

- ✅ Rate limiting per user
- ✅ File size validation
- ✅ Group-only mode
- ✅ Input sanitization
- ✅ Error handling

## 📊 Monitoring

Bot menyediakan health check endpoint:
- `http://localhost:8080/` - Status check
- `http://localhost:8080/health` - Health check

## 🐛 Troubleshooting

**Bot tidak merespon di grup:**
- Pastikan bot sudah ditambahkan ke grup
- Pastikan bot di-mention atau di-reply

**Rate limit error:**
- Tunggu beberapa detik
- Default: 10 pesan per menit per user

**Markdown error:**
- Bot otomatis fallback ke plain text
- Check logs untuk detail

## 📄 License

MIT License

## 🤝 Contributing

Contributions welcome! Please read CONTRIBUTING.md first.
