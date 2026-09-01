from __future__ import annotations

import os
from pathlib import Path

from .secureio import directory_fd


APP_NAME = "goalwatch"


def _home() -> Path:
    return Path.home()


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config")) / APP_NAME


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", _home() / ".local/state")) / APP_NAME


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        base = f"/run/user/{os.getuid()}"
    return Path(base) / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


def config_lock_file() -> Path:
    return config_dir() / ".config.lock"


def runtime_state_file() -> Path:
    return runtime_dir() / "state.json"


def metrics_file() -> Path:
    return state_dir() / "metrics.sqlite3"


def ensure_private_dir(path: Path) -> None:
    with directory_fd(path, create=True, private=True):
        pass
