from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

from .paths import config_dir, config_file, config_lock_file, ensure_private_dir


DEFAULT_TOOLS = "Codex, Browser, Obsidian and any tool useful to the goal."
DEFAULT_CONFIG = {
    "version": 1,
    "interval_minutes": 5,
    "model": "gemini-flash-lite-latest",
    "markdown_file": "",
    "markdown_source": "none",
    "daily_file": "",
    "daily_date": "",
    "manual_override_date": "",
    "default_tools": DEFAULT_TOOLS,
}


class ConfigError(ValueError):
    pass


def _normalized(raw: object) -> dict:
    data = deepcopy(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        for key in DEFAULT_CONFIG:
            if key in raw:
                data[key] = raw[key]

    try:
        interval = int(data["interval_minutes"])
    except (TypeError, ValueError):
        interval = DEFAULT_CONFIG["interval_minutes"]
    data["interval_minutes"] = min(1440, max(1, interval))

    model = str(data["model"] or "").strip()
    data["model"] = model or DEFAULT_CONFIG["model"]
    for key in (
        "markdown_file",
        "markdown_source",
        "daily_file",
        "daily_date",
        "manual_override_date",
        "default_tools",
    ):
        data[key] = str(data[key] or "")
    if data["markdown_source"] not in {"none", "daily", "manual"}:
        data["markdown_source"] = "none"
    if not data["default_tools"].strip():
        data["default_tools"] = DEFAULT_TOOLS
    return data


def load_config() -> dict:
    path = config_file()
    try:
        with path.open("r", encoding="utf-8") as handle:
            return _normalized(json.load(handle))
    except (FileNotFoundError, OSError, ValueError):
        return deepcopy(DEFAULT_CONFIG)


def _write_atomic(path: Path, data: dict) -> None:
    ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _locked() -> Iterator[None]:
    ensure_private_dir(config_dir())
    with config_lock_file().open("a+", encoding="utf-8") as lock:
        config_lock_file().chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def save_config(data: dict) -> dict:
    clean = _normalized(data)
    with _locked():
        _write_atomic(config_file(), clean)
    return clean


def mutate_config(change: Callable[[dict], None]) -> dict:
    with _locked():
        current = load_config()
        change(current)
        clean = _normalized(current)
        _write_atomic(config_file(), clean)
        return clean


def set_value(name: str, value: str) -> dict:
    if name == "interval_minutes":
        try:
            number = int(value)
        except ValueError as error:
            raise ConfigError("Interval must be a whole number.") from error
        if not 1 <= number <= 1440:
            raise ConfigError("Interval must be between 1 and 1440 minutes.")
        return mutate_config(lambda config: config.update(interval_minutes=number))

    if name == "model":
        clean = value.strip()
        if not clean or len(clean) > 160 or any(ch.isspace() for ch in clean):
            raise ConfigError("Model must be a non-empty Gemini model identifier.")
        return mutate_config(lambda config: config.update(model=clean))

    if name == "markdown_file":
        return set_manual_file(value)

    raise ConfigError(f"Unknown setting: {name}")


def _absolute_markdown(path: str) -> str:
    clean = os.path.abspath(os.path.expanduser(path.strip())) if path.strip() else ""
    if clean and Path(clean).suffix.lower() != ".md":
        raise ConfigError("Markdown File must end in .md.")
    return clean


def set_manual_file(path: str, override_date: str | None = None) -> dict:
    clean = _absolute_markdown(path)
    today = override_date or date.today().isoformat()

    def change(config: dict) -> None:
        config["markdown_file"] = clean
        config["markdown_source"] = "manual" if clean else "none"
        config["manual_override_date"] = today if clean else ""

    return mutate_config(change)


def set_daily_file(vault: str, relative_file: str, daily_date: str) -> dict:
    vault_path = Path(os.path.abspath(os.path.expanduser(vault.strip()))).resolve()
    relative = Path(relative_file.strip())
    if not vault.strip() or not relative_file.strip():
        raise ConfigError("Vault and daily file are required.")
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".md":
        raise ConfigError("Daily file must be a vault-relative Markdown path.")
    try:
        date.fromisoformat(daily_date)
    except ValueError as error:
        raise ConfigError("Daily date must use YYYY-MM-DD.") from error
    target = (vault_path / relative).resolve(strict=False)
    try:
        target.relative_to(vault_path)
    except ValueError as error:
        raise ConfigError("Daily file must remain inside the vault.") from error
    absolute = str(target)

    def change(config: dict) -> None:
        previous_daily_date = config.get("daily_date", "")
        config["daily_file"] = absolute
        config["daily_date"] = daily_date
        same_day_manual = (
            config.get("markdown_source") == "manual"
            and config.get("manual_override_date") == daily_date
            and previous_daily_date in {"", daily_date}
        )
        if not same_day_manual:
            config["markdown_file"] = absolute
            config["markdown_source"] = "daily"
            config["manual_override_date"] = ""

    return mutate_config(change)
