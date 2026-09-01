from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .capture import capture_desktop
from .config import ConfigError, load_config, set_daily_file, set_manual_file, set_value
from .daemon import run_daemon
from .gemini import GeminiClient
from .goals import read_latest_goal
from .metrics import Metrics
from .paths import config_file, metrics_file, runtime_state_file
from .secrets import SecretError, clear_api_key, get_api_key, has_api_key, set_api_key
from .state import read_state, write_off_state, write_state


SERVICE = "goalwatch.service"
OBSIDIAN_CONFIGS = (
    "~/.config/obsidian/obsidian.json",
    "~/.var/app/md.obsidian.Obsidian/config/obsidian.json",
    "~/snap/obsidian/current/.config/obsidian/obsidian.json",
)


def emit(data: object) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def systemctl(*arguments: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *arguments],
        capture_output=capture,
        text=True,
        timeout=15,
        check=False,
    )


def service_active() -> bool:
    try:
        return systemctl("is-active", "--quiet", SERVICE).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def notify_reload() -> None:
    if not service_active():
        return
    try:
        systemctl("kill", "--kill-whom=main", "--signal=HUP", SERVICE)
    except (OSError, subprocess.SubprocessError):
        pass


def command_service(action: str) -> int:
    if action == "toggle":
        action = "stop" if service_active() else "start"
    result = systemctl(action, SERVICE)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or f"Could not {action} GoalWatch."
        print(message, file=sys.stderr)
        return 1
    if action == "stop":
        write_off_state()
    return 0


def public_config() -> dict:
    config = load_config()
    return {
        "interval_minutes": config["interval_minutes"],
        "model": config["model"],
        "markdown_file": config["markdown_file"],
        "markdown_source": config["markdown_source"],
        "daily_file": config["daily_file"],
        "daily_date": config["daily_date"],
        "api_key_set": has_api_key(),
    }


def refresh_off_state() -> None:
    if service_active():
        return
    current = read_state()
    config = load_config()
    try:
        key_set = has_api_key()
    except SecretError:
        key_set = False
    current.update(
        {
            "state": "OFF",
            "active": False,
            "interval_minutes": config["interval_minutes"],
            "model": config["model"],
            "markdown_file": config["markdown_file"],
            "markdown_source": config["markdown_source"],
            "api_key_set": key_set,
            "next_check_at": "",
            "alert": {"active": False, "complement": "", "shown_at": ""},
        }
    )
    try:
        goal = read_latest_goal(config["markdown_file"], config["default_tools"])
    except Exception:
        goal = None
    current["goal"] = goal.description if goal else ""
    current["tools"] = goal.tools if goal else ""
    write_state(current)


def status() -> dict:
    current = read_state()
    active = service_active()
    current["active"] = active
    if not active:
        current["state"] = "OFF"
        current["next_check_at"] = ""
        current["alert"] = {"active": False, "complement": "", "shown_at": ""}
    return current


def obsidian_vaults() -> list[str]:
    found: list[tuple[bool, int, str]] = []
    for candidate in OBSIDIAN_CONFIGS:
        path = Path(os.path.expanduser(candidate))
        try:
            entries = json.loads(path.read_text(encoding="utf-8")).get("vaults", {})
        except (OSError, ValueError, AttributeError):
            continue
        for entry in entries.values():
            if not isinstance(entry, dict) or not entry.get("path"):
                continue
            vault = os.path.abspath(os.path.expanduser(str(entry["path"])))
            if Path(vault).is_dir():
                found.append((bool(entry.get("open")), int(entry.get("ts") or 0), vault))
    found.sort(reverse=True)
    result: list[str] = []
    for _open, _timestamp, vault in found:
        if vault not in result:
            result.append(vault)
    return result


def command_config(arguments: argparse.Namespace) -> int:
    if arguments.config_action == "show":
        emit(public_config())
        return 0
    if arguments.config_action == "set":
        set_value(arguments.name, arguments.value)
        notify_reload()
        emit(public_config())
        return 0
    if arguments.config_action == "set-api-key":
        if sys.stdin.isatty():
            print("Read the new API key from stdin; do not pass it as an argument.", file=sys.stderr)
            return 2
        set_api_key(sys.stdin.readline())
        notify_reload()
        emit({"api_key_set": True})
        return 0
    if arguments.config_action == "clear-api-key":
        clear_api_key()
        notify_reload()
        emit({"api_key_set": False})
        return 0
    return 2


def command_file(arguments: argparse.Namespace) -> int:
    if arguments.file_action == "current":
        if arguments.vault and arguments.file:
            relative = Path(arguments.file)
            if relative.is_absolute() or ".." in relative.parts:
                raise ConfigError("Current file must be vault-relative.")
            vault = Path(arguments.vault).expanduser().resolve()
            resolved = (vault / relative).resolve(strict=False)
            try:
                resolved.relative_to(vault)
            except ValueError as error:
                raise ConfigError("Current file must remain inside the vault.") from error
            target = str(resolved)
        else:
            target = arguments.path
        config = set_manual_file(target)
    else:
        config = set_daily_file(arguments.vault, arguments.file, arguments.date)
    notify_reload()
    emit({
        "markdown_file": config["markdown_file"],
        "markdown_source": config["markdown_source"],
    })
    return 0


def command_dismiss() -> int:
    if service_active():
        result = systemctl("kill", "--kill-whom=main", "--signal=USR1", SERVICE)
        return 0 if result.returncode == 0 else 1
    current = read_state()
    current.update({
        "state": "OFF",
        "active": False,
        "alert": {"active": False, "complement": "", "shown_at": ""},
    })
    write_state(current)
    return 0


def command_run_once() -> int:
    config = load_config()
    goal = read_latest_goal(config["markdown_file"], config["default_tools"])
    key = get_api_key()
    if not goal:
        print("No valid Current Goal block was found.", file=sys.stderr)
        return 1
    if not key:
        print("No Gemini API key is set.", file=sys.stderr)
        return 1
    image = capture_desktop()
    decision = GeminiClient(key, config["model"]).classify(goal, image)
    emit({
        "alert": decision.alert,
        "complement": decision.complement,
        "latency_ms": decision.latency_ms,
        "image_bytes": len(image),
        "prompt_tokens": decision.prompt_tokens,
        "output_tokens": decision.output_tokens,
    })
    return 0


def command_debug(arguments: argparse.Namespace) -> int:
    current = read_state()
    if arguments.debug_action == "alert":
        current.update(
            {
                "state": "ALERT",
                "active": service_active(),
                "goal": arguments.goal,
                "alert": {
                    "active": True,
                    "complement": arguments.complement,
                    "shown_at": "synthetic",
                },
            }
        )
        write_state(current)
    else:
        current.update(
            {
                "state": "WATCHING" if service_active() else "OFF",
                "active": service_active(),
                "alert": {"active": False, "complement": "", "shown_at": ""},
            }
        )
        write_state(current)
    return 0


def command_doctor() -> int:
    checks = {
        "omarchy": shutil.which("omarchy") is not None,
        "quickshell": shutil.which("quickshell") is not None,
        "python3": shutil.which("python3") is not None,
        "grim": shutil.which("grim") is not None,
        "secret_tool": shutil.which("secret-tool") is not None,
        "systemctl_user": systemctl("show-environment").returncode == 0,
        "api_key_set": False,
    }
    try:
        checks["api_key_set"] = has_api_key()
    except SecretError:
        pass
    emit({"ok": all(value for key, value in checks.items() if key != "api_key_set"), "checks": checks})
    return 0 if all(value for key, value in checks.items() if key != "api_key_set") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="goalwatch", description="GoalWatch — Stay on goal.")
    parser.add_argument("--version", action="version", version=f"GoalWatch {__version__}")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("start", "stop", "restart", "toggle"):
        sub.add_parser(name)
    sub.add_parser("daemon")
    sub.add_parser("status")
    sub.add_parser("dismiss")
    sub.add_parser("run-once")
    sub.add_parser("doctor")
    sub.add_parser("state-off", help=argparse.SUPPRESS)

    paths = sub.add_parser("paths")
    paths.add_argument("--json", action="store_true")

    metrics = sub.add_parser("metrics")
    metrics.add_argument("--json", action="store_true")

    obsidian = sub.add_parser("obsidian-vaults")
    obsidian.add_argument("--json", action="store_true")

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_action", required=True)
    config_sub.add_parser("show")
    setting = config_sub.add_parser("set")
    setting.add_argument("name", choices=("interval_minutes", "model", "markdown_file"))
    setting.add_argument("value")
    config_sub.add_parser("set-api-key")
    config_sub.add_parser("clear-api-key")

    file_parser = sub.add_parser("file")
    file_sub = file_parser.add_subparsers(dest="file_action", required=True)
    current = file_sub.add_parser("current")
    current.add_argument("path", nargs="?", default="")
    current.add_argument("--vault", default="")
    current.add_argument("--file", default="")
    daily = file_sub.add_parser("daily")
    daily.add_argument("--vault", required=True)
    daily.add_argument("--file", required=True)
    daily.add_argument("--date", default=date.today().isoformat())

    debug = sub.add_parser("debug")
    debug_sub = debug.add_subparsers(dest="debug_action", required=True)
    alert = debug_sub.add_parser("alert")
    alert.add_argument("--goal", default="Finish the current goal")
    alert.add_argument(
        "--complement",
        default="This activity is clearly unrelated to the current goal.",
    )
    debug_sub.add_parser("clear")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.action in {"start", "stop", "restart", "toggle"}:
            return command_service(arguments.action)
        if arguments.action == "daemon":
            return run_daemon()
        if arguments.action == "status":
            emit(status())
            return 0
        if arguments.action == "dismiss":
            return command_dismiss()
        if arguments.action == "run-once":
            return command_run_once()
        if arguments.action == "doctor":
            return command_doctor()
        if arguments.action == "state-off":
            write_off_state()
            return 0
        if arguments.action == "paths":
            emit({
                "config": str(config_file()),
                "state": str(runtime_state_file()),
                "metrics": str(metrics_file()),
            })
            return 0
        if arguments.action == "metrics":
            store = Metrics()
            try:
                emit(store.summary())
            finally:
                store.close()
            return 0
        if arguments.action == "obsidian-vaults":
            emit(obsidian_vaults())
            return 0
        if arguments.action == "config":
            result = command_config(arguments)
            refresh_off_state()
            return result
        if arguments.action == "file":
            result = command_file(arguments)
            refresh_off_state()
            return result
        if arguments.action == "debug":
            return command_debug(arguments)
    except (ConfigError, SecretError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 2
