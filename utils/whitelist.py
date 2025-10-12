import asyncio
import json
import os
from typing import List, Set

_WL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "whitelist.json")
_lock = asyncio.Lock()


def _ensure_dir():
    os.makedirs(os.path.dirname(_WL_PATH), exist_ok=True)


def _read_file() -> Set[int]:
    if not os.path.exists(_WL_PATH):
        return set()
    try:
        with open(_WL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {int(x) for x in data}
    except Exception:
        pass
    return set()


def _write_file(groups: Set[int]) -> None:
    tmp = _WL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(groups), f, ensure_ascii=False, indent=2)
    os.replace(tmp, _WL_PATH)


async def add_group(chat_id: int) -> None:
    async with _lock:
        _ensure_dir()
        groups = _read_file()
        groups.add(int(chat_id))
        _write_file(groups)


async def remove_group(chat_id: int) -> None:
    async with _lock:
        _ensure_dir()
        groups = _read_file()
        groups.discard(int(chat_id))
        _write_file(groups)


async def list_groups() -> List[int]:
    async with _lock:
        return sorted(_read_file())


async def is_whitelisted(chat_id: int) -> bool:
    async with _lock:
        groups = _read_file()
        return int(chat_id) in groups
