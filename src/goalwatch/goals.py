from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_TOOLS


GOAL_RE = re.compile(r"^\s*>\s*Current Goal:\s*(?P<goal>.+?)\s*$", re.IGNORECASE)
TOOLS_RE = re.compile(r"^\s*>\s*Available Tools:\s*(?P<tools>.+?)\s*$", re.IGNORECASE)
MAX_GOAL_CHARS = 2_000
MAX_TOOLS_CHARS = 3_000


@dataclass(frozen=True)
class Goal:
    description: str
    tools: str


class GoalReadError(RuntimeError):
    pass


def parse_latest_goal(markdown: str, default_tools: str = DEFAULT_TOOLS) -> Goal | None:
    lines = markdown.splitlines()
    found: list[Goal] = []
    fallback_tools = default_tools.strip()
    if not fallback_tools or len(fallback_tools) > MAX_TOOLS_CHARS:
        fallback_tools = DEFAULT_TOOLS
    for index, line in enumerate(lines):
        match = GOAL_RE.match(line)
        if not match:
            continue
        description = match.group("goal").strip()
        if not description or len(description) > MAX_GOAL_CHARS:
            continue
        tools = ""
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            tools_match = TOOLS_RE.match(candidate)
            if tools_match:
                tools = tools_match.group("tools").strip()
                break
            if GOAL_RE.match(candidate):
                break
            if candidate.strip() and not re.match(r"^\s*>\s*$", candidate):
                break
            cursor += 1
        if len(tools) > MAX_TOOLS_CHARS:
            continue
        found.append(Goal(description=description, tools=tools or fallback_tools))
    return found[-1] if found else None


def read_latest_goal(path: str, default_tools: str = DEFAULT_TOOLS) -> Goal | None:
    if not path:
        return None
    target = Path(path).expanduser()
    try:
        if target.is_symlink() or not target.is_file():
            return None
        if target.stat().st_size > 10 * 1024 * 1024:
            raise GoalReadError("Markdown file is larger than 10 MiB.")
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise GoalReadError("Markdown file is not valid UTF-8.") from error
    except OSError as error:
        raise GoalReadError("Markdown file could not be read.") from error
    return parse_latest_goal(text, default_tools)
