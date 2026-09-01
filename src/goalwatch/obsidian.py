from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import load_config, set_obsidian_integration


PLUGIN_ID = "goalwatch"
REGISTRIES = (
    "~/.config/obsidian/obsidian.json",
    "~/.var/app/md.obsidian.Obsidian/config/obsidian.json",
    "~/snap/obsidian/current/.config/obsidian/obsidian.json",
)
REQUIRED_PLUGIN_FILES = ("main.js", "manifest.json")


class ObsidianError(RuntimeError):
    pass


def obsidian_installed() -> bool:
    if shutil.which("obsidian") or Path("/snap/bin/obsidian").exists():
        return True
    candidates = (
        "~/.local/share/applications/obsidian.desktop",
        "~/.local/share/flatpak/exports/share/applications/md.obsidian.Obsidian.desktop",
        "/usr/share/applications/obsidian.desktop",
        "/var/lib/flatpak/exports/share/applications/md.obsidian.Obsidian.desktop",
    )
    return any(Path(os.path.expanduser(name)).is_file() for name in candidates)


def obsidian_running() -> bool:
    proc = Path("/proc")
    try:
        processes = proc.iterdir()
    except OSError:
        return False
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            name = (process / "comm").read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if "obsidian" in name:
            return True
    return False


def discover_vaults() -> list[Path]:
    entries: list[tuple[bool, int, str, Path]] = []
    for name in REGISTRIES:
        registry = Path(os.path.expanduser(name))
        try:
            parsed = json.loads(registry.read_text(encoding="utf-8"))
            vaults = parsed.get("vaults", {})
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(vaults, dict):
            continue
        for item in vaults.values():
            if not isinstance(item, dict) or not item.get("path"):
                continue
            candidate = Path(str(item["path"])).expanduser().resolve()
            if candidate.is_dir() and (candidate / ".obsidian").is_dir():
                entries.append(
                    (bool(item.get("open")), int(item.get("ts") or 0), str(candidate), candidate)
                )
    entries.sort(reverse=True)
    result: list[Path] = []
    for _open, _timestamp, _name, path in entries:
        if path not in result:
            result.append(path)
    return result


def default_plugin_source() -> Path:
    installed = Path(__file__).resolve().parent / "_obsidian"
    if installed.is_dir():
        return installed
    checkout = Path(__file__).resolve().parents[2] / "integrations" / "obsidian" / PLUGIN_ID
    return checkout


def _validate_vault(vault: Path) -> Path:
    candidate = vault.expanduser().resolve()
    obsidian = candidate / ".obsidian"
    if not candidate.is_dir() or not obsidian.is_dir():
        raise ObsidianError(f"Not an Obsidian vault: {candidate}")
    if obsidian.is_symlink():
        raise ObsidianError(f"The Obsidian settings directory cannot be a symlink: {obsidian}")
    return candidate


def _plugin_destination(vault: Path) -> Path:
    plugins = vault / ".obsidian" / "plugins"
    if plugins.is_symlink():
        raise ObsidianError(f"The Obsidian plugins directory cannot be a symlink: {plugins}")
    plugins.mkdir(parents=True, exist_ok=True)
    return plugins / PLUGIN_ID


def _atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _community_plugins(vault: Path, strict: bool = True) -> tuple[Path, list[str]]:
    path = vault / ".obsidian" / "community-plugins.json"
    if path.is_symlink():
        if strict:
            raise ObsidianError(f"Refusing to replace a symlinked plugin registry: {path}")
        return path, []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return path, []
    except (OSError, ValueError) as error:
        if strict:
            raise ObsidianError(f"Could not read {path} without risking other plugins.") from error
        return path, []
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        if strict:
            raise ObsidianError(f"Could not update invalid plugin registry: {path}")
        return path, []
    return path, parsed


def _remove_entry(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def plugin_connected(vault: Path) -> bool:
    try:
        candidate = _validate_vault(vault)
        destination = candidate / ".obsidian" / "plugins" / PLUGIN_ID
        if destination.is_symlink() or not all(
            (destination / name).is_file() for name in REQUIRED_PLUGIN_FILES
        ):
            return False
        _path, plugins = _community_plugins(candidate)
        return PLUGIN_ID in plugins
    except (ObsidianError, OSError):
        return False


def install_plugin(source: Path, vault: Path) -> None:
    source = source.expanduser().resolve()
    vault = _validate_vault(vault)
    if not source.is_dir() or not all((source / name).is_file() for name in REQUIRED_PLUGIN_FILES):
        raise ObsidianError("The packaged GoalWatch Obsidian companion is incomplete.")
    destination = _plugin_destination(vault)
    if destination.is_symlink():
        raise ObsidianError(f"Refusing to replace a symlinked plugin directory: {destination}")
    plugins_path, plugins = _community_plugins(vault)
    next_plugins = plugins if PLUGIN_ID in plugins else [*plugins, PLUGIN_ID]

    stage = destination.parent / f".{PLUGIN_ID}.install-{os.getpid()}"
    backup = destination.parent / f".{PLUGIN_ID}.previous-{os.getpid()}"
    if stage.exists() or stage.is_symlink() or backup.exists() or backup.is_symlink():
        raise ObsidianError("A previous Obsidian companion operation needs manual cleanup.")
    shutil.copytree(source, stage)
    try:
        if destination.exists():
            destination.rename(backup)
        stage.rename(destination)
        if next_plugins != plugins:
            _atomic_json(plugins_path, next_plugins)
    except BaseException:
        if destination.exists():
            _remove_entry(destination)
        if backup.exists():
            backup.rename(destination)
        if stage.exists():
            shutil.rmtree(stage)
        raise
    if backup.exists():
        _remove_entry(backup)


def uninstall_plugin(vault: Path) -> list[str]:
    warnings: list[str] = []
    try:
        vault = _validate_vault(vault)
        plugins = vault / ".obsidian" / "plugins"
        if plugins.is_symlink():
            raise ObsidianError(f"The Obsidian plugins directory cannot be a symlink: {plugins}")
        destination = plugins / PLUGIN_ID
    except (ObsidianError, OSError) as error:
        return [str(error)]
    try:
        _remove_entry(destination)
    except OSError:
        warnings.append(f"Could not remove {destination}.")
    try:
        plugins_path, plugins = _community_plugins(vault)
        next_plugins = [item for item in plugins if item != PLUGIN_ID]
        if next_plugins != plugins:
            _atomic_json(plugins_path, next_plugins)
    except (ObsidianError, OSError) as error:
        warnings.append(str(error))
    return warnings


def _try_live_command(vault: Path, command: str) -> bool:
    executable = shutil.which("obsidian")
    if not executable or not obsidian_running():
        return False
    try:
        result = subprocess.run(
            [executable, f"vault={vault.name}", command, f"id={PLUGIN_ID}"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = f"{result.stdout}\n{result.stderr}".lower()
    rejected = ("not enabled", "not found", "failed", "unable", "unknown command", "error:")
    return result.returncode == 0 and not any(marker in output for marker in rejected)


def integration_status(config: dict | None = None) -> dict:
    current = config or load_config()
    vaults = discover_vaults()
    installed = obsidian_installed() or obsidian_running()
    configured_name = str(current.get("obsidian_vault") or "")
    configured = Path(configured_name).expanduser() if configured_name else None
    vault = configured if configured and configured.is_dir() else (vaults[0] if vaults else None)
    connected = bool(vault and plugin_connected(vault))
    enabled = current.get("obsidian_enabled") is True
    if enabled and not installed:
        message = "Obsidian is not installed. Turn off sync or install Obsidian."
    elif enabled and connected and vault:
        message = f"Connected to {vault.name}."
    elif enabled and vault:
        message = "Obsidian Sync needs repair. Tap once to reconnect."
    elif enabled:
        message = "The connected Obsidian vault is no longer available."
    elif not installed:
        message = "Obsidian is not installed. Manual goals work without it."
    elif vaults:
        message = "Optional. Uses your most recent local vault."
    else:
        message = "Open or create an Obsidian vault before connecting."
    return {
        "enabled": enabled,
        "connected": enabled and connected and installed,
        "available": bool(vaults),
        "installed": installed,
        "running": obsidian_running(),
        "vault": str(vault) if vault else "",
        "message": message,
    }


def enable_integration(vaults: list[Path] | None = None, source: Path | None = None) -> dict:
    if not obsidian_installed() and not obsidian_running():
        raise ObsidianError(
            "Obsidian is not installed. Install and open it once, or keep using a manual goal."
        )
    candidates = [_validate_vault(path) for path in (vaults or [])]
    if not candidates:
        config = load_config()
        configured_name = str(config.get("obsidian_vault") or "")
        configured = Path(configured_name).expanduser() if configured_name else None
        if configured and configured.is_dir() and (configured / ".obsidian").is_dir():
            candidates = [_validate_vault(configured)]
        else:
            candidates = discover_vaults()
    if not candidates:
        raise ObsidianError(
            "No local Obsidian vault is registered. Open or create a vault, then try again."
        )

    vault = candidates[0]
    was_connected = plugin_connected(vault)
    install_plugin(source or default_plugin_source(), vault)
    try:
        set_obsidian_integration(True, str(vault))
    except BaseException:
        if not was_connected:
            uninstall_plugin(vault)
        raise
    running = obsidian_running()
    live = not running or _try_live_command(vault, "plugin:reload")
    result = integration_status()
    result.update(
        {
            "ok": True,
            "reload_required": running and not live,
            "message": (
                f"Connected to {vault.name}. Restart Obsidian once to load the companion."
                if running and not live
                else f"Connected to {vault.name}."
            ),
        }
    )
    return result


def disable_integration(vaults: list[Path] | None = None) -> dict:
    config = load_config()
    targets: list[Path] = []
    configured_name = str(config.get("obsidian_vault") or "")
    configured = Path(configured_name).expanduser() if configured_name else None
    for candidate in [*(vaults or []), configured, *discover_vaults()]:
        if candidate is None or not candidate.is_dir() or candidate in targets:
            continue
        targets.append(candidate)

    live_unloaded = True
    if obsidian_running() and targets:
        live_unloaded = _try_live_command(targets[0], "plugin:disable")
    set_obsidian_integration(False)
    warnings: list[str] = []
    for vault in targets:
        warnings.extend(uninstall_plugin(vault))
    result = integration_status()
    result.update(
        {
            "ok": True,
            "reload_required": obsidian_running() and not live_unloaded,
            "warnings": warnings,
            "message": (
                "Obsidian Sync is off. Restart Obsidian once to unload the companion."
                if obsidian_running() and not live_unloaded
                else "Obsidian Sync is off. Your manual goal is active."
            ),
        }
    )
    return result
