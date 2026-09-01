#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path


PLUGIN_ID = "goalwatch"
REGISTRIES = (
    "~/.config/obsidian/obsidian.json",
    "~/.var/app/md.obsidian.Obsidian/config/obsidian.json",
    "~/snap/obsidian/current/.config/obsidian/obsidian.json",
)


def discover_vaults() -> list[Path]:
    entries: list[tuple[bool, int, Path]] = []
    for name in REGISTRIES:
        registry = Path(os.path.expanduser(name))
        try:
            vaults = json.loads(registry.read_text(encoding="utf-8")).get("vaults", {})
        except (OSError, ValueError, AttributeError):
            continue
        for item in vaults.values():
            if not isinstance(item, dict) or not item.get("path"):
                continue
            candidate = Path(str(item["path"])).expanduser().resolve()
            if candidate.is_dir():
                entries.append((bool(item.get("open")), int(item.get("ts") or 0), candidate))
    entries.sort(reverse=True)
    result: list[Path] = []
    for _open, _timestamp, path in entries:
        if path not in result:
            result.append(path)
    return result


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
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


def community_plugins(vault: Path) -> tuple[Path, list[str]]:
    path = vault / ".obsidian" / "community-plugins.json"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        plugins = [str(item) for item in parsed] if isinstance(parsed, list) else []
    except (OSError, ValueError):
        plugins = []
    return path, plugins


def install(source: Path, vault: Path) -> None:
    obsidian = vault / ".obsidian"
    if not obsidian.is_dir():
        raise RuntimeError(f"Not an Obsidian vault: {vault}")
    destination = obsidian / "plugins" / PLUGIN_ID
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / f".{PLUGIN_ID}.install-{os.getpid()}"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(source, stage)
    backup = destination.parent / f".{PLUGIN_ID}.previous-{os.getpid()}"
    try:
        if destination.exists():
            destination.rename(backup)
        stage.rename(destination)
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        if destination.exists() and not backup.exists():
            shutil.rmtree(destination)
        if backup.exists():
            backup.rename(destination)
        if stage.exists():
            shutil.rmtree(stage)
        raise
    plugins_path, plugins = community_plugins(vault)
    if PLUGIN_ID not in plugins:
        plugins.append(PLUGIN_ID)
        atomic_json(plugins_path, plugins)


def uninstall(vault: Path) -> None:
    destination = vault / ".obsidian" / "plugins" / PLUGIN_ID
    if destination.is_dir():
        shutil.rmtree(destination)
    plugins_path, plugins = community_plugins(vault)
    next_plugins = [item for item in plugins if item != PLUGIN_ID]
    if next_plugins != plugins:
        atomic_json(plugins_path, next_plugins)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or remove the GoalWatch Obsidian plugin.")
    parser.add_argument("action", choices=("install", "uninstall", "discover"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--vault", action="append", type=Path, default=[])
    args = parser.parse_args()
    vaults = [path.expanduser().resolve() for path in args.vault] or discover_vaults()
    if args.action == "discover":
        print(json.dumps([str(path) for path in vaults]))
        return 0
    if not vaults:
        print("No registered Obsidian vault was found.")
        return 3
    if args.action == "install":
        if not args.source or not args.source.is_dir():
            parser.error("--source is required for install")
        for vault in vaults:
            install(args.source.resolve(), vault)
            print(f"Installed GoalWatch for Obsidian in {vault}")
    else:
        for vault in vaults:
            uninstall(vault)
            print(f"Removed GoalWatch for Obsidian from {vault}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
