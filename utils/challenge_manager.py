"""Challenge manager: tracks selections, pending challenges, and scores (JSON-persisted)"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
import json
import os

from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class PendingChallenge:
    chat_id: int
    user_id: int
    language: str
    difficulty: str  # easy|medium|hard
    prompt: str  # challenge text shown to the user


class ChallengeManager:
    def __init__(self) -> None:
        # (chat_id, user_id) -> {"language": str}
        self._selections: Dict[Tuple[int, int], Dict[str, str]] = {}
        # message_id -> PendingChallenge
        self._pending: Dict[int, PendingChallenge] = {}
        # chat_id -> {user_id -> points(float)}
        self._scores: Dict[int, Dict[int, float]] = {}
        # chat_id -> {user_id -> display_name}
        self._users: Dict[int, Dict[int, str]] = {}

        base_dir = "/home/han/MyWorkspace/Telegram-Dev-Bot/data"
        self._store_path = os.path.join(base_dir, "challenges.json")
        try:
            os.makedirs(base_dir, exist_ok=True)
        except Exception:
            pass
        self._load()

    # Selection flow helpers
    def set_language(self, chat_id: int, user_id: int, language: str) -> None:
        self._selections[(chat_id, user_id)] = {"language": language}
        logger.debug("Set language for (%s,%s)=%s", chat_id, user_id, language)

    def get_language(self, chat_id: int, user_id: int) -> Optional[str]:
        data = self._selections.get((chat_id, user_id))
        return data.get("language") if data else None

    def clear_selection(self, chat_id: int, user_id: int) -> None:
        self._selections.pop((chat_id, user_id), None)

    # Pending challenge mapping (message replies)
    def add_pending(self, message_id: int, payload: PendingChallenge) -> None:
        self._pending[message_id] = payload
        logger.debug("Added pending challenge for msg %s in chat %s", message_id, payload.chat_id)

    def get_pending(self, message_id: int) -> Optional[PendingChallenge]:
        return self._pending.get(message_id)

    def remove_pending(self, message_id: int) -> None:
        self._pending.pop(message_id, None)

    # Scoring
    def add_points(self, chat_id: int, user_id: int, points: float, display_name: Optional[str] = None) -> float:
        chat_scores = self._scores.setdefault(chat_id, {})
        chat_scores[user_id] = chat_scores.get(user_id, 0.0) + points
        if display_name:
            self._users.setdefault(chat_id, {})[user_id] = display_name
        self._save()
        logger.info(
            "Updated points: chat=%s user=%s points=%.2f total=%.2f",
            chat_id,
            user_id,
            points,
            chat_scores[user_id],
        )
        return chat_scores[user_id]

    def get_total_points(self, chat_id: int, user_id: int) -> float:
        return self._scores.get(chat_id, {}).get(user_id, 0.0)

    def leaderboard(self, chat_id: int, limit: int = 10) -> List[Tuple[int, float]]:
        scores = self._scores.get(chat_id, {})
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:limit]

    def leaderboard_with_names(self, chat_id: int, limit: int = 10) -> List[Tuple[str, float]]:
        ranked = self.leaderboard(chat_id, limit)
        users = self._users.get(chat_id, {})
        out: List[Tuple[str, float]] = []
        for uid, score in ranked:
            label = users.get(uid, f"ID {uid}")
            out.append((label, score))
        return out

    # Persistence
    def _load(self) -> None:
        try:
            if os.path.exists(self._store_path):
                with open(self._store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                scores = data.get("scores", {})
                users = data.get("users", {})
                # convert keys back to int
                self._scores = {int(k): {int(uk): float(uv) for uk, uv in v.items()} for k, v in scores.items()}
                self._users = {int(k): {int(uk): str(uv) for uk, uv in v.items()} for k, v in users.items()}
                logger.info("Loaded challenge data: chats=%d", len(self._scores))
        except Exception as e:
            logger.error("Failed to load challenge data: %s", e, exc_info=True)

    def _save(self) -> None:
        try:
            payload = {
                "version": 1,
                "scores": {str(k): {str(uk): uv for uk, uv in v.items()} for k, v in self._scores.items()},
                "users": {str(k): {str(uk): uv for uk, uv in v.items()} for k, v in self._users.items()},
            }
            with open(self._store_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save challenge data: %s", e, exc_info=True)


# Global instance
challenge_manager = ChallengeManager()
