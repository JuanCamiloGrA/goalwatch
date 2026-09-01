from __future__ import annotations

import shutil
import subprocess

from .process import run_bounded


ATTRIBUTES = ["service", "goalwatch", "account", "gemini"]


class SecretError(RuntimeError):
    pass


def _tool() -> str:
    path = shutil.which("secret-tool")
    if not path:
        raise SecretError("Secret Service is unavailable. Install libsecret.")
    return path


def get_api_key() -> str:
    try:
        result = run_bounded(
            [_tool(), "lookup", *ATTRIBUTES],
            timeout=8,
            stdout_limit=1024,
            stderr_limit=32 * 1024,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SecretError("Could not read the API key from Secret Service.") from error
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def has_api_key() -> bool:
    return bool(get_api_key())


def set_api_key(value: str) -> None:
    key = value.strip()
    if len(key) < 16 or len(key) > 512 or any(ch.isspace() for ch in key):
        raise SecretError("API key is not valid.")
    try:
        result = run_bounded(
            [_tool(), "store", "--label=GoalWatch Gemini API key", *ATTRIBUTES],
            input_data=key + "\n",
            timeout=15,
            stdout_limit=32 * 1024,
            stderr_limit=32 * 1024,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SecretError("Could not save the API key to Secret Service.") from error
    if result.returncode != 0:
        raise SecretError("Secret Service rejected the API key.")


def clear_api_key() -> None:
    try:
        run_bounded(
            [_tool(), "clear", *ATTRIBUTES],
            timeout=8,
            stdout_limit=32 * 1024,
            stderr_limit=32 * 1024,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        pass
