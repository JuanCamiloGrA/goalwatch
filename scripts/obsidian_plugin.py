#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goalwatch.config import ConfigError  # noqa: E402
from goalwatch.obsidian import (  # noqa: E402
    ObsidianError,
    disable_integration,
    discover_vaults,
    enable_integration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or remove the GoalWatch Obsidian companion.")
    parser.add_argument("action", choices=("install", "uninstall", "discover"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--vault", action="append", type=Path, default=[])
    arguments = parser.parse_args()
    if arguments.action == "discover":
        print(json.dumps([str(path) for path in discover_vaults()]))
        return 0
    try:
        if arguments.action == "install":
            result = enable_integration(arguments.vault or None, arguments.source)
        else:
            result = disable_integration(arguments.vault or None)
    except (ObsidianError, ConfigError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 3
    print(result["message"])
    for warning in result.get("warnings", []):
        print(f"Warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
