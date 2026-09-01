from __future__ import annotations

import json
import math
import shutil
import subprocess

from .process import ProcessOutputLimitError, run_bounded


MAX_LONG_EDGE = 1920
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class CaptureError(RuntimeError):
    pass


def _session_locked() -> bool:
    checker = shutil.which("omarchy-hyprland-session-locked")
    if not checker:
        return False
    try:
        result = run_bounded(
            [checker], timeout=2, stdout_limit=4096, stderr_limit=4096
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _monitors() -> list[dict]:
    hyprctl = shutil.which("hyprctl")
    if not hyprctl:
        return []
    try:
        result = run_bounded(
            [hyprctl, "monitors", "-j"],
            timeout=3,
            stdout_limit=1024 * 1024,
            stderr_limit=64 * 1024,
            text=True,
        )
        parsed = json.loads(result.stdout) if result.returncode == 0 else []
        return parsed if isinstance(parsed, list) else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def _capture_scale(monitors: list[dict]) -> float:
    active = [m for m in monitors if not m.get("disabled", False)]
    if not active:
        return 1.0
    left = min(float(m.get("x", 0)) for m in active)
    top = min(float(m.get("y", 0)) for m in active)
    right = max(float(m.get("x", 0)) + float(m.get("width", 0)) for m in active)
    bottom = max(float(m.get("y", 0)) + float(m.get("height", 0)) for m in active)
    longest = max(1.0, right - left, bottom - top)
    scale = min(1.0, MAX_LONG_EDGE / longest)
    return math.floor(scale * 1000) / 1000


def outputs_available(monitors: list[dict] | None = None) -> bool:
    if monitors is None:
        monitors = _monitors()
    if not monitors:
        return True
    active = [m for m in monitors if not m.get("disabled", False)]
    if not active:
        return False
    statuses = [m.get("dpmsStatus") for m in active if "dpmsStatus" in m]
    return not statuses or any(bool(status) for status in statuses)


def _jpeg_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise CaptureError("Desktop capture was not a JPEG image.")
    cursor = 2
    while cursor + 9 < len(data):
        if data[cursor] != 0xFF:
            cursor += 1
            continue
        marker = data[cursor + 1]
        cursor += 2
        if marker in {0xD8, 0xD9}:
            continue
        if cursor + 2 > len(data):
            break
        length = int.from_bytes(data[cursor:cursor + 2], "big")
        if marker in range(0xC0, 0xC4) and cursor + 7 <= len(data):
            height = int.from_bytes(data[cursor + 3:cursor + 5], "big")
            width = int.from_bytes(data[cursor + 5:cursor + 7], "big")
            return width, height
        if length < 2:
            break
        cursor += length
    raise CaptureError("Desktop capture dimensions could not be read.")


def _run_grim(grim: str, scale: float) -> bytes:
    command = [grim, "-s", f"{scale:.3f}", "-t", "jpeg", "-q", "65", "-"]
    try:
        result = run_bounded(
            command,
            timeout=10,
            stdout_limit=MAX_IMAGE_BYTES,
            stderr_limit=64 * 1024,
        )
    except ProcessOutputLimitError as error:
        raise CaptureError("Desktop capture exceeded the request-size guard.") from error
    except (OSError, subprocess.SubprocessError) as error:
        raise CaptureError("Desktop capture failed.") from error
    if result.returncode != 0 or not result.stdout:
        raise CaptureError("Desktop capture failed.")
    return result.stdout


def capture_desktop() -> bytes:
    grim = shutil.which("grim")
    if not grim:
        raise CaptureError("grim is not installed.")
    if _session_locked():
        raise CaptureError("Session is locked.")
    monitors = _monitors()
    if monitors and not outputs_available(monitors):
        raise CaptureError("Displays are powered off.")
    scale = _capture_scale(monitors)
    data = _run_grim(grim, scale)
    width, height = _jpeg_size(data)
    if max(width, height) > MAX_LONG_EDGE:
        scale *= MAX_LONG_EDGE / max(width, height)
        data = _run_grim(grim, scale)
        width, height = _jpeg_size(data)
    if max(width, height) > MAX_LONG_EDGE:
        raise CaptureError("Desktop capture exceeded the dimension guard.")
    if len(data) > MAX_IMAGE_BYTES:
        raise CaptureError("Desktop capture exceeded the request-size guard.")
    return data
