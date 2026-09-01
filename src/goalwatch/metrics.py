from __future__ import annotations

import os
import sqlite3
import statistics
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .paths import metrics_file
from .secureio import directory_fd


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  stopped_at TEXT
);
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  occurred_at TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('on_goal','off_goal','error','skipped')),
  model TEXT NOT NULL,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  image_bytes INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  goal_hash TEXT NOT NULL DEFAULT '',
  error_code TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY,
  check_id INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
  shown_at TEXT NOT NULL,
  acknowledged_at TEXT,
  recovered_at TEXT
);
CREATE INDEX IF NOT EXISTS checks_occurred_idx ON checks(occurred_at);
CREATE INDEX IF NOT EXISTS alerts_recovered_idx ON alerts(recovered_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Metrics:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or metrics_file()
        self._directory = directory_fd(self.path.parent, create=True, private=True)
        self._directory_fd = self._directory.__enter__()
        try:
            for name in (self.path.name, f"{self.path.name}-wal", f"{self.path.name}-shm"):
                try:
                    info = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise OSError(f"Refusing unsafe metrics path: {name}")
            descriptor_path = f"/proc/self/fd/{self._directory_fd}/{self.path.name}"
            self.connection = sqlite3.connect(descriptor_path, timeout=5)
        except BaseException:
            self._directory.__exit__(None, None, None)
            raise
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.executescript(SCHEMA)
            self.connection.commit()
            os.chmod(
                self.path.name,
                0o600,
                dir_fd=self._directory_fd,
                follow_symlinks=False,
            )
        except BaseException:
            self.connection.close()
            self._directory.__exit__(None, None, None)
            raise

    def close(self) -> None:
        self.connection.close()
        self._directory.__exit__(None, None, None)

    def start_session(self) -> int:
        cursor = self.connection.execute(
            "INSERT INTO sessions(started_at) VALUES(?)", (utc_now(),)
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def stop_session(self, session_id: int) -> None:
        self.connection.execute(
            "UPDATE sessions SET stopped_at=? WHERE id=? AND stopped_at IS NULL",
            (utc_now(), session_id),
        )
        self.connection.commit()

    def record_check(
        self,
        session_id: int,
        outcome: str,
        model: str,
        *,
        latency_ms: int = 0,
        image_bytes: int = 0,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        goal_hash: str = "",
        error_code: str = "",
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO checks(
              session_id, occurred_at, outcome, model, latency_ms, image_bytes,
              prompt_tokens, output_tokens, goal_hash, error_code
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                utc_now(),
                outcome,
                model,
                max(0, int(latency_ms)),
                max(0, int(image_bytes)),
                max(0, int(prompt_tokens)),
                max(0, int(output_tokens)),
                goal_hash,
                error_code,
            ),
        )
        check_id = int(cursor.lastrowid)
        if outcome == "on_goal":
            self.connection.execute(
                "UPDATE alerts SET recovered_at=? WHERE recovered_at IS NULL", (utc_now(),)
            )
        self.connection.commit()
        return check_id

    def create_alert(self, check_id: int) -> int:
        cursor = self.connection.execute(
            "INSERT INTO alerts(check_id, shown_at) VALUES(?,?)", (check_id, utc_now())
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def acknowledge_alert(self, alert_id: int) -> None:
        self.connection.execute(
            "UPDATE alerts SET acknowledged_at=? WHERE id=? AND acknowledged_at IS NULL",
            (utc_now(), alert_id),
        )
        self.connection.commit()

    def prune(self, days: int = 90) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        self.connection.execute("DELETE FROM checks WHERE occurred_at < ?", (cutoff,))
        self.connection.execute(
            "DELETE FROM sessions WHERE stopped_at IS NOT NULL AND stopped_at < ?", (cutoff,)
        )
        self.connection.commit()

    def summary(self, session_id: int | None = None) -> dict:
        local_now = datetime.now().astimezone()
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        start_utc = local_start.astimezone(timezone.utc).isoformat(timespec="seconds")
        end_utc = local_end.astimezone(timezone.utc).isoformat(timespec="seconds")
        rows = self.connection.execute(
            """
            SELECT outcome, latency_ms, image_bytes, prompt_tokens, output_tokens, occurred_at
            FROM checks WHERE occurred_at>=? AND occurred_at<?
            ORDER BY id
            """,
            (start_utc, end_utc),
        ).fetchall()
        on_goal = sum(row["outcome"] == "on_goal" for row in rows)
        off_goal = sum(row["outcome"] == "off_goal" for row in rows)
        valid = on_goal + off_goal
        latencies = [row["latency_ms"] for row in rows if row["latency_ms"] > 0]
        alerts = self.connection.execute(
            """
            SELECT shown_at, acknowledged_at, recovered_at FROM alerts
            WHERE shown_at>=? AND shown_at<?
            """,
            (start_utc, end_utc),
        ).fetchall()
        recovery_seconds: list[int] = []
        for row in alerts:
            if row["recovered_at"]:
                shown = datetime.fromisoformat(row["shown_at"])
                recovered = datetime.fromisoformat(row["recovered_at"])
                recovery_seconds.append(max(0, int((recovered - shown).total_seconds())))
        session_started = ""
        if session_id is not None:
            session = self.connection.execute(
                "SELECT started_at FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            session_started = session["started_at"] if session else ""
        streak_started = ""
        if session_id is not None:
            last_classified = self.connection.execute(
                """
                SELECT id, outcome FROM checks
                WHERE session_id=? AND outcome IN ('on_goal','off_goal')
                ORDER BY id DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if last_classified and last_classified["outcome"] == "on_goal":
                start = self.connection.execute(
                    """
                    SELECT occurred_at FROM checks
                    WHERE session_id=? AND outcome='on_goal' AND id>(
                      SELECT COALESCE(MAX(id), 0) FROM checks
                      WHERE session_id=? AND outcome='off_goal'
                    )
                    ORDER BY id LIMIT 1
                    """,
                    (session_id, session_id),
                ).fetchone()
                streak_started = start["occurred_at"] if start else ""
        return {
            "focus_score": round(on_goal * 100 / valid) if valid else 0,
            "checks_today": len(rows),
            "on_goal_today": on_goal,
            "off_goal_today": off_goal,
            "alerts_today": len(alerts),
            "median_latency_ms": round(statistics.median(latencies)) if latencies else 0,
            "prompt_tokens_today": sum(row["prompt_tokens"] for row in rows),
            "output_tokens_today": sum(row["output_tokens"] for row in rows),
            "image_bytes_today": sum(row["image_bytes"] for row in rows),
            "average_return_seconds": round(statistics.mean(recovery_seconds)) if recovery_seconds else 0,
            "session_started_at": session_started,
            "streak_started_at": streak_started,
        }


def reset_metrics(path: Path | None = None) -> None:
    target = path or metrics_file()
    try:
        with directory_fd(target.parent, create=False, private=True) as directory:
            for name in (target.name, f"{target.name}-wal", f"{target.name}-shm"):
                try:
                    os.unlink(name, dir_fd=directory)
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        pass
