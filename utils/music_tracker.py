import asyncio
import time
import uuid
import html
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from telegram import Bot

from .telegram_safe import edit_message_text_safe


@dataclass
class MusicTask:
    id: str
    filename: str
    stage: str = "download"  # download | upload | done | error
    percent: float = 0.0
    downloaded: int = 0
    total: Optional[int] = None
    speed_bps: Optional[float] = None


@dataclass
class MusicUserTracker:
    chat_id: int
    user_id: int
    user_display: str
    group_display: str
    message_id: Optional[int] = None
    tasks: Dict[str, MusicTask] = field(default_factory=dict)
    task_handles: Dict[str, asyncio.Task] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_render: float = 0.0


class MusicTracker:
    def __init__(self, per_user_limit: int = 4):
        self._per_user_limit = per_user_limit
        self._trackers: Dict[Tuple[int, int], MusicUserTracker] = {}

    def _key(self, chat_id: int, user_id: int) -> Tuple[int, int]:
        return (chat_id, user_id)

    async def ensure_tracker(self, chat_id: int, user_id: int, user_display: str, group_display: str) -> MusicUserTracker:
        key = self._key(chat_id, user_id)
        tracker = self._trackers.get(key)
        if tracker is None:
            tracker = MusicUserTracker(chat_id=chat_id, user_id=user_id, user_display=user_display, group_display=group_display)
            self._trackers[key] = tracker
        else:
            tracker.user_display = user_display
            tracker.group_display = group_display
        return tracker

    def start_task(self, tracker: MusicUserTracker, filename: str) -> MusicTask:
        t = MusicTask(id=str(uuid.uuid4()), filename=filename)
        tracker.tasks[t.id] = t
        return t

    def bind_handle(self, tracker: MusicUserTracker, task_id: str, handle: asyncio.Task):
        tracker.task_handles[task_id] = handle

    async def set_message_id(self, tracker: MusicUserTracker, message_id: int):
        async with tracker.lock:
            tracker.message_id = message_id

    async def update_task(self, bot: Bot, tracker: MusicUserTracker, task_id: str, *,
                          stage: Optional[str] = None,
                          downloaded: Optional[int] = None,
                          total: Optional[int] = None,
                          speed_bps: Optional[float] = None):
        async with tracker.lock:
            task = tracker.tasks.get(task_id)
            if not task:
                return
            if stage:
                task.stage = stage
            if downloaded is not None:
                task.downloaded = downloaded
            if total is not None:
                task.total = total
            if speed_bps is not None:
                task.speed_bps = speed_bps
            if task.total and task.total > 0:
                task.percent = max(0.0, min(100.0, (task.downloaded / task.total) * 100.0))
            elif stage == "done":
                task.percent = 100.0
            await self._render(bot, tracker)

    async def finish_task(self, bot: Bot, tracker: MusicUserTracker, task_id: str, *, success: bool):
        async with tracker.lock:
            task = tracker.tasks.get(task_id)
            if not task:
                return
            task.stage = "done" if success else "error"
            task.percent = 100.0 if success else task.percent
            tracker.tasks.pop(task_id, None)
            tracker.task_handles.pop(task_id, None)
            await self._render(bot, tracker)

    def _bar(self, p: float, width: int = 20) -> str:
        p = max(0.0, min(100.0, p))
        filled = int(round((p / 100.0) * width))
        return f"[{'█' * filled}{'░' * (width - filled)}] {p:5.1f}%"

    def _esc(self, s: str) -> str:
        return html.escape(s or "")

    def _format(self, tracker: MusicUserTracker) -> str:
        lines = []
        lines.append(f"🎵 <b>Task</b> [{self._esc(tracker.user_display)}] <b>Music</b>")
        lines.append(f"👥 <b>Group</b> [{self._esc(tracker.group_display)}]")
        active = list(tracker.tasks.values())
        if len(active) > 1:
            lines.append(f"📦 [Download {len(active)}] File")
        for t in active:
            icon = "📥" if t.stage == "download" else ("📤" if t.stage == "upload" else "✅")
            lines.append(f"{icon} <code>{self._esc(t.filename)}</code>")
            lines.append(self._bar(t.percent))
        if not active:
            lines.append("—")
        return "\n".join(lines)

    async def _render(self, bot: Bot, tracker: MusicUserTracker):
        now = time.monotonic()
        if tracker.message_id is None:
            return
        if now - tracker._last_render < 0.4:
            return
        tracker._last_render = now
        try:
            await edit_message_text_safe(
                bot,
                chat_id=tracker.chat_id,
                message_id=tracker.message_id,
                text=self._format(tracker),
                parse_mode="HTML",
            )
        except Exception:
            pass


music_tracker = MusicTracker(per_user_limit=4)
