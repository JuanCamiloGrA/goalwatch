from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from .paths import ensure_private_dir, runtime_state_file


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


def write_state(data: dict, path: Path | None = None) -> dict:
    target = path or runtime_state_file()
    ensure_private_dir(target.parent)
    merged = deepcopy(BASE_STATE)
    merged.update(data)
    if not isinstance(merged.get("alert"), dict):
        merged["alert"] = deepcopy(BASE_STATE["alert"])
    if not isinstance(merged.get("metrics"), dict):
        merged["metrics"] = {}
    fd, temporary = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return merged


def read_state(path: Path | None = None) -> dict:
    target = path or runtime_state_file()
    try:
        with target.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
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
