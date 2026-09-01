from __future__ import annotations

import fcntl
import os
import sqlite3
import statistics
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .database import open_bound_sqlite
from .paths import metrics_file
from .secureio import directory_fd, open_lock_at


METRICS_RETENTION_DAYS = 90
MAX_CHECK_ROWS = 30_000
MAX_SESSION_ROWS = 5_000
MAX_METRICS_DB_BYTES = 16 * 1024 * 1024
MAX_METRICS_WAL_BYTES = 4 * 1024 * 1024


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
        self._closed = False
        self._directory = directory_fd(self.path.parent, create=True, private=True)
        self._directory_fd = self._directory.__enter__()
        self._lock_fd = -1
        self._database_fd = -1
        try:
            self._lock_fd = open_lock_at(self._directory_fd, ".metrics.lock")
            fcntl.flock(self._lock_fd, fcntl.LOCK_SH)
            for name in (f"{self.path.name}-wal", f"{self.path.name}-shm"):
                try:
                    info = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise OSError(f"Refusing unsafe metrics path: {name}")
            try:
                self.connection, self._database_fd = open_bound_sqlite(
                    self._directory_fd,
                    self.path.name,
                    timeout=5,
                )
            except OSError as error:
                raise OSError(f"Refusing unsafe metrics path: {self.path.name}") from error
        except BaseException:
            if self._lock_fd >= 0:
                os.close(self._lock_fd)
            self._directory.__exit__(None, None, None)
            raise
        try:
            self.connection.row_factory = sqlite3.Row
            self._configure_size_limits()
            self.connection.executescript(SCHEMA)
            self.prune(METRICS_RETENTION_DAYS)
            self.connection.commit()
        except BaseException:
            self.connection.close()
            os.close(self._database_fd)
            os.close(self._lock_fd)
            self._directory.__exit__(None, None, None)
            raise

    def close(self) -> None:
        if self._closed:
            return
        self.connection.close()
        os.close(self._database_fd)
        os.close(self._lock_fd)
        self._directory.__exit__(None, None, None)
        self._closed = True

    def _configure_size_limits(self) -> None:
        page_size = int(self.connection.execute("PRAGMA page_size").fetchone()[0])
        max_pages = max(1, MAX_METRICS_DB_BYTES // page_size)
        self.connection.execute(f"PRAGMA max_page_count={max_pages}")
        self.connection.execute("PRAGMA wal_autocheckpoint=250")
        self.connection.execute(f"PRAGMA journal_size_limit={MAX_METRICS_WAL_BYTES}")
        if os.fstat(self._database_fd).st_size > MAX_METRICS_DB_BYTES:
            raise OSError("Metrics database exceeds its size quota.")

    def _trim_rows(self, *, check_limit: int, session_limit: int, protected_session: int = 0) -> None:
        self.connection.execute(
            """
            DELETE FROM checks WHERE id IN (
              SELECT id FROM checks ORDER BY id DESC LIMIT -1 OFFSET ?
            )
            """,
            (max(0, check_limit),),
        )
        self.connection.execute(
            """
            DELETE FROM sessions WHERE id IN (
              SELECT id FROM sessions WHERE id != ?
              ORDER BY id DESC LIMIT -1 OFFSET ?
            )
            """,
            (int(protected_session), max(0, session_limit)),
        )

    def start_session(self) -> int:
        self._trim_rows(
            check_limit=MAX_CHECK_ROWS,
            session_limit=MAX_SESSION_ROWS - 1,
        )
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
        self._trim_rows(
            check_limit=MAX_CHECK_ROWS - 1,
            session_limit=MAX_SESSION_ROWS - 1,
            protected_session=session_id,
        )
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

    def prune(self, days: int = METRICS_RETENTION_DAYS) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        self.connection.execute("DELETE FROM checks WHERE occurred_at < ?", (cutoff,))
        self.connection.execute(
            "DELETE FROM sessions WHERE stopped_at IS NOT NULL AND stopped_at < ?", (cutoff,)
        )
        self._trim_rows(
            check_limit=MAX_CHECK_ROWS,
            session_limit=MAX_SESSION_ROWS,
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
            lock = open_lock_at(directory, ".metrics.lock")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                for name in (target.name, f"{target.name}-wal", f"{target.name}-shm"):
                    try:
                        os.unlink(name, dir_fd=directory)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(lock)
    except FileNotFoundError:
        pass
