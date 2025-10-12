# Dev log

## 2025-10-12

- Fix: AI API 422 (Unprocessable Entity) due to request schema mismatch to Bytez.
- Change: In `services/ai_service.py` switched primary payload to `messages` with top-level `max_tokens`/`temperature`, with fallbacks to `messages+params` and `input` variants. Hardened response extraction and sanitized leaked role/system lines.
- Result: Bot now returns non-empty responses (HTTP 200) in group chats; verified at ~12:44.
