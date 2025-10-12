import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from telegram import Bot

from .telegram_safe import edit_message_text_safe


@dataclass
class DownloadTask:
    id: str
    filename: str
    stage: str = "download"  # "download" | "upload" | "done" | "error"
    percent: float = 0.0
    downloaded: int = 0
    total: Optional[int] = None
    speed_bps: Optional[float] = None


@dataclass
class UserTracker:
    chat_id: int
    user_id: int
    user_display: str
    group_display: str
    message_id: Optional[int] = None
    tasks: Dict[str, DownloadTask] = field(default_factory=dict)
    task_handles: Dict[str, asyncio.Task] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_render: float = 0.0


class DownloadTracker:
    def __init__(self, per_user_limit: int = 2):
        self._per_user_limit = per_user_limit
        self._trackers: Dict[Tuple[int, int], UserTracker] = {}

    def _key(self, chat_id: int, user_id: int) -> Tuple[int, int]:
        return (chat_id, user_id)

    def can_start(self, chat_id: int, user_id: int) -> bool:
        tracker = self._trackers.get(self._key(chat_id, user_id))
        if not tracker:
            return True
        active = sum(1 for t in tracker.tasks.values() if t.stage not in ("done", "error"))
        return active < self._per_user_limit

    async def ensure_tracker(self, chat_id: int, user_id: int, user_display: str, group_display: str) -> UserTracker:
        key = self._key(chat_id, user_id)
        tracker = self._trackers.get(key)
        if tracker is None:
            tracker = UserTracker(chat_id=chat_id, user_id=user_id, user_display=user_display, group_display=group_display)
            self._trackers[key] = tracker
        else:
            # keep latest display names
            tracker.user_display = user_display
            tracker.group_display = group_display
        return tracker

    def start_task(self, tracker: UserTracker, filename: str) -> DownloadTask:
        task = DownloadTask(id=str(uuid.uuid4()), filename=filename)
        tracker.tasks[task.id] = task
        return task

    def bind_handle(self, tracker: UserTracker, task_id: str, handle: asyncio.Task):
        tracker.task_handles[task_id] = handle

    async def set_message_id(self, tracker: UserTracker, message_id: int):
        async with tracker.lock:
            tracker.message_id = message_id

    async def update_task(self, bot: Bot, tracker: UserTracker, task_id: str, *,
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

            # compute percent
            if task.total and task.total > 0:
                task.percent = max(0.0, min(100.0, (task.downloaded / task.total) * 100.0))
            elif stage == "done":
                task.percent = 100.0

            await self._render(bot, tracker)

    async def finish_task(self, bot: Bot, tracker: UserTracker, task_id: str, *, success: bool):
        async with tracker.lock:
            task = tracker.tasks.get(task_id)
            if not task:
                return
            task.stage = "done" if success else "error"
            task.percent = 100.0 if success else task.percent
            # remove finished task from list for cleaner view
            tracker.tasks.pop(task_id, None)
            tracker.task_handles.pop(task_id, None)
            await self._render(bot, tracker)

    async def cancel_all(self, bot: Bot, tracker: UserTracker):
        # cancel active asyncio tasks
        to_cancel = [tid for tid, t in tracker.tasks.items() if t.stage not in ("done", "error")]
        for tid in to_cancel:
            handle = tracker.task_handles.get(tid)
            if handle and not handle.done():
                handle.cancel()
        # Rendering will be driven by task exception handlers calling finish_task

    def _progress_bar(self, percent: float, width: int = 20) -> str:
        p = max(0.0, min(100.0, percent))
        filled = int(round((p / 100.0) * width))
        return f"[{'█' * filled}{'░' * (width - filled)}] {p:5.1f}%"

    def _format(self, tracker: UserTracker) -> str:
        lines = []
        lines.append(f"Task [{tracker.user_display}] Mirror.")
        lines.append(f"Group [{tracker.group_display}]")
        active = list(tracker.tasks.values())
        if len(active) > 1:
            lines.append(f"[Download {len(active)}] File")
        for t in active:
            lines.append(f"[{t.filename}]")
            lines.append(self._progress_bar(t.percent))
        if not active:
            lines.append("Tidak ada tugas unduhan aktif.")
        return "\n".join(lines)

    async def _render(self, bot: Bot, tracker: UserTracker):
        now = time.monotonic()
        # Throttle to avoid hitting rate limits
        if tracker.message_id is None:
            return
        if now - tracker._last_render < 0.4:
            return
        tracker._last_render = now
        text = self._format(tracker)
        try:
            await edit_message_text_safe(
                bot,
                chat_id=tracker.chat_id,
                message_id=tracker.message_id,
                text=text,
            )
        except Exception:
            # Ignore edit failures silently
            pass


# Global singleton
download_tracker = DownloadTracker(per_user_limit=2)
