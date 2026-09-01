from __future__ import annotations

import shutil
import subprocess


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
        result = subprocess.run(
            [_tool(), "lookup", *ATTRIBUTES],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
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
        result = subprocess.run(
            [_tool(), "store", "--label=GoalWatch Gemini API key", *ATTRIBUTES],
            input=key + "\n",
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SecretError("Could not save the API key to Secret Service.") from error
    if result.returncode != 0:
        raise SecretError("Secret Service rejected the API key.")


def clear_api_key() -> None:
    try:
        subprocess.run(
            [_tool(), "clear", *ATTRIBUTES],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
