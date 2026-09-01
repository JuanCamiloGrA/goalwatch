from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path

from .paths import audit_dir, audit_file
from .secureio import atomic_write_bytes_at, directory_fd, open_lock_at


IMAGE_NAME = re.compile(r"^request-[0-9]{8}\.jpg$")
OUTCOMES = {"pending", "on_goal", "off_goal", "error"}
MAX_QUERY_CHARS = 200
MAX_PAGE_SIZE = 100

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY,
  requested_at TEXT NOT NULL,
  completed_at TEXT,
  model TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  goal TEXT NOT NULL,
  tools TEXT NOT NULL,
  request_json TEXT NOT NULL,
  image_file TEXT NOT NULL,
  image_bytes INTEGER NOT NULL,
  image_sha256 TEXT NOT NULL,
  http_status INTEGER NOT NULL DEFAULT 0,
  response_headers_json TEXT NOT NULL DEFAULT '{}',
  response_body BLOB NOT NULL DEFAULT X'',
  response_bytes INTEGER NOT NULL DEFAULT 0,
  response_sha256 TEXT NOT NULL DEFAULT '',
  response_truncated INTEGER NOT NULL DEFAULT 0,
  outcome TEXT NOT NULL CHECK(outcome IN ('pending','on_goal','off_goal','error')),
  error_code TEXT NOT NULL DEFAULT '',
  latency_ms INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS audit_requested_idx ON requests(requested_at DESC);
CREATE INDEX IF NOT EXISTS audit_outcome_idx ON requests(outcome, requested_at DESC);
"""


class AuditError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditStore:
    def __init__(self, path: Path | None = None, *, exclusive: bool = False) -> None:
        self.path = path or audit_file()
        self.directory_path = self.path.parent if path else audit_dir()
        self.exclusive = exclusive
        self._closed = False
        self._directory = directory_fd(self.directory_path, create=True, private=True)
        self._directory_fd = self._directory.__enter__()
        self._lock_fd = -1
        try:
            self._lock_fd = open_lock_at(self._directory_fd, ".audit.lock")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            for name in (self.path.name, f"{self.path.name}-wal", f"{self.path.name}-shm"):
                try:
                    info = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise AuditError(f"Refusing unsafe audit path: {name}")
            descriptor_path = f"/proc/self/fd/{self._directory_fd}/{self.path.name}"
            self.connection = sqlite3.connect(descriptor_path, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.executescript(SCHEMA)
            self.connection.commit()
            os.chmod(
                self.path.name,
                0o600,
                dir_fd=self._directory_fd,
                follow_symlinks=False,
            )
            if exclusive:
                self._remove_orphan_images()
        except Exception as error:
            connection = getattr(self, "connection", None)
            if connection is not None:
                connection.close()
            if self._lock_fd >= 0:
                os.close(self._lock_fd)
            self._directory.__exit__(None, None, None)
            if isinstance(error, AuditError):
                raise
            raise AuditError("Could not open the private audit archive.") from error

    def close(self) -> None:
        if self._closed:
            return
        self.connection.close()
        os.close(self._lock_fd)
        self._directory.__exit__(None, None, None)
        self._closed = True

    def __enter__(self) -> AuditStore:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def _remove_orphan_images(self) -> None:
        referenced = {
            row[0]
            for row in self.connection.execute("SELECT image_file FROM requests").fetchall()
        }
        directory = f"/proc/self/fd/{self._directory_fd}"
        for entry in os.scandir(directory):
            if IMAGE_NAME.fullmatch(entry.name) and entry.name not in referenced:
                try:
                    os.unlink(entry.name, dir_fd=self._directory_fd)
                except FileNotFoundError:
                    pass

    def begin(
        self,
        *,
        model: str,
        endpoint: str,
        goal: str,
        tools: str,
        request: dict,
        image: bytes,
    ) -> int:
        image_name = ""
        try:
            image_digest = hashlib.sha256(image).hexdigest()
            cursor = self.connection.execute(
                """
                INSERT INTO requests(
                  requested_at, model, endpoint, goal, tools, request_json,
                  image_file, image_bytes, image_sha256, outcome
                ) VALUES(?,?,?,?,?,?,?,?,?, 'pending')
                """,
                (
                    utc_now(), model, endpoint, goal, tools, "", "",
                    len(image), image_digest,
                ),
            )
            record_id = int(cursor.lastrowid)
            image_name = f"request-{record_id:08d}.jpg"
            document = dict(request)
            document["screenshot"] = {
                "file": image_name,
                "mimeType": "image/jpeg",
                "bytes": len(image),
                "sha256": image_digest,
                "note": "The exact image bytes are stored in the adjacent audit file.",
            }
            atomic_write_bytes_at(self._directory_fd, image_name, image)
            cursor = self.connection.execute(
                "UPDATE requests SET request_json=?, image_file=? WHERE id=?",
                (json.dumps(document, ensure_ascii=False, indent=2), image_name, record_id),
            )
            self.connection.commit()
        except Exception as error:
            self.connection.rollback()
            if image_name:
                try:
                    os.unlink(image_name, dir_fd=self._directory_fd)
                except FileNotFoundError:
                    pass
            raise AuditError("Could not persist the request audit record.") from error
        return record_id

    def finish(
        self,
        record_id: int,
        *,
        outcome: str,
        raw_response: bytes,
        http_status: int = 0,
        response_headers: dict | None = None,
        response_truncated: bool = False,
        error_code: str = "",
        latency_ms: int = 0,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        if outcome not in OUTCOMES - {"pending"}:
            raise AuditError("Invalid audit outcome.")
        try:
            cursor = self.connection.execute(
                """
                UPDATE requests SET
                  completed_at=?, http_status=?, response_headers_json=?,
                  response_body=?, response_bytes=?, response_sha256=?,
                  response_truncated=?, outcome=?, error_code=?, latency_ms=?,
                  prompt_tokens=?, output_tokens=?
                WHERE id=?
                """,
                (
                    utc_now(),
                    max(0, int(http_status)),
                    json.dumps(response_headers or {}, ensure_ascii=False, sort_keys=True),
                    sqlite3.Binary(raw_response),
                    len(raw_response),
                    hashlib.sha256(raw_response).hexdigest() if raw_response else "",
                    bool(response_truncated),
                    outcome,
                    str(error_code or ""),
                    max(0, int(latency_ms)),
                    max(0, int(prompt_tokens)),
                    max(0, int(output_tokens)),
                    int(record_id),
                ),
            )
            if cursor.rowcount != 1:
                raise AuditError("Audit record was not found.")
            self.connection.commit()
        except (OSError, sqlite3.Error, AuditError) as error:
            self.connection.rollback()
            if isinstance(error, AuditError):
                raise
            raise AuditError("Could not persist the model response audit record.") from error

    def query(
        self,
        *,
        outcome: str = "all",
        query: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        if outcome != "all" and outcome not in OUTCOMES:
            raise AuditError("Unknown audit outcome filter.")
        clean_query = str(query or "").strip()[:MAX_QUERY_CHARS]
        page_size = min(MAX_PAGE_SIZE, max(1, int(limit)))
        page_offset = max(0, int(offset))
        clauses: list[str] = []
        parameters: list[object] = []
        if outcome != "all":
            clauses.append("outcome=?")
            parameters.append(outcome)
        if clean_query:
            clauses.append(
                "(goal LIKE ? OR tools LIKE ? OR model LIKE ? OR error_code LIKE ? "
                "OR CAST(response_body AS TEXT) LIKE ?)"
            )
            needle = f"%{clean_query}%"
            parameters.extend([needle] * 5)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(
            self.connection.execute(
                f"SELECT count(*) FROM requests{where}", parameters
            ).fetchone()[0]
        )
        rows = self.connection.execute(
            f"""
            SELECT id, requested_at, completed_at, model, goal, outcome,
                   error_code, image_bytes, response_bytes, response_truncated,
                   http_status, latency_ms
            FROM requests{where}
            ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            [*parameters, page_size, page_offset],
        ).fetchall()
        return {
            "total": total,
            "limit": page_size,
            "offset": page_offset,
            "records": [dict(row) for row in rows],
        }

    def get(self, record_id: int) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM requests WHERE id=?", (int(record_id),)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        raw = bytes(result.pop("response_body") or b"")
        try:
            response = raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            response = base64.b64encode(raw).decode("ascii")
            encoding = "base64"
        image_name = str(result.get("image_file") or "")
        image_path = ""
        if IMAGE_NAME.fullmatch(image_name):
            try:
                info = os.stat(
                    image_name,
                    dir_fd=self._directory_fd,
                    follow_symlinks=False,
                )
                if stat.S_ISREG(info.st_mode):
                    image_path = str(self.directory_path.resolve() / image_name)
            except OSError:
                pass
        result["image_path"] = image_path
        result["raw_response"] = response
        result["raw_response_encoding"] = encoding
        return result

    def clear(self) -> int:
        if not self.exclusive:
            raise AuditError("Clearing audit data requires an exclusive archive lock.")
        rows = self.connection.execute("SELECT image_file FROM requests").fetchall()
        count = int(self.connection.execute("SELECT count(*) FROM requests").fetchone()[0])
        try:
            self.connection.execute("DELETE FROM requests")
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            raise AuditError("Could not clear the audit database.") from error
        for row in rows:
            name = str(row[0] or "")
            if not IMAGE_NAME.fullmatch(name):
                continue
            try:
                os.unlink(name, dir_fd=self._directory_fd)
            except FileNotFoundError:
                pass
        return count
