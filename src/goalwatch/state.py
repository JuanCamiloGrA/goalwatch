from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .paths import runtime_state_file
from .secureio import atomic_write_text_at, directory_fd, read_text_at


BASE_STATE = {
    "version": 2,
    "state": "OFF",
    "active": False,
    "goal": "",
    "tools": "",
    "goal_source": "manual",
    "manual_goal": "",
    "manual_tools": "",
    "obsidian_enabled": False,
    "obsidian_connected": False,
    "obsidian_vault": "",
    "obsidian_message": "",
    "markdown_file": "",
    "markdown_source": "none",
    "interval_minutes": 5,
    "model": "gemini-flash-lite-latest",
    "api_key_set": False,
    "last_check_at": "",
    "next_check_at": "",
    "last_outcome": "",
    "error": "",
    "alert": {"active": False, "complement": "", "shown_at": ""},
    "metrics": {},
}
MAX_STATE_BYTES = 1024 * 1024


def write_state(data: dict, path: Path | None = None) -> dict:
    target = path or runtime_state_file()
    merged = deepcopy(BASE_STATE)
    merged.update(data)
    if not isinstance(merged.get("alert"), dict):
        merged["alert"] = deepcopy(BASE_STATE["alert"])
    if not isinstance(merged.get("metrics"), dict):
        merged["metrics"] = {}
    content = json.dumps(merged, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if len(content.encode("utf-8")) > MAX_STATE_BYTES:
        raise OSError("Runtime state exceeded its size limit.")
    with directory_fd(target.parent, create=True, private=True) as directory:
        atomic_write_text_at(directory, target.name, content)
    return merged


def read_state(path: Path | None = None) -> dict:
    target = path or runtime_state_file()
    try:
        with directory_fd(target.parent, create=False, private=True) as directory:
            parsed = json.loads(read_text_at(directory, target.name, limit=MAX_STATE_BYTES))
        if isinstance(parsed, dict):
            merged = deepcopy(BASE_STATE)
            merged.update(parsed)
            return merged
    except (FileNotFoundError, OSError, ValueError):
        pass
    return deepcopy(BASE_STATE)


def write_off_state() -> dict:
    previous = read_state()
    return write_state(
        {
            **previous,
            "state": "OFF",
            "active": False,
            "next_check_at": "",
            "error": "",
            "alert": deepcopy(BASE_STATE["alert"]),
        }
    )
