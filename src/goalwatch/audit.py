from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .database import open_bound_sqlite
from .paths import audit_dir, audit_file
from .secureio import atomic_write_bytes_at, directory_fd, open_lock_at


IMAGE_NAME = re.compile(r"^request-[0-9]{8}\.jpg$")
OUTCOMES = {"pending", "on_goal", "off_goal", "error"}
MAX_QUERY_CHARS = 200
MAX_PAGE_SIZE = 100
AUDIT_RETENTION_DAYS = 7
MAX_AUDIT_ROWS = 2_000
MAX_AUDIT_CONTENT_BYTES = 512 * 1024 * 1024
MAX_AUDIT_RESPONSE_BYTES = 224 * 1024 * 1024
MAX_AUDIT_DB_BYTES = 256 * 1024 * 1024
MAX_AUDIT_WAL_BYTES = 8 * 1024 * 1024

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
        self._write_lock_fd = -1
        self._database_fd = -1
        try:
            self._lock_fd = open_lock_at(self._directory_fd, ".audit.lock")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            self._write_lock_fd = open_lock_at(self._directory_fd, ".audit.write.lock")
            for name in (f"{self.path.name}-wal", f"{self.path.name}-shm"):
                try:
                    info = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise AuditError(f"Refusing unsafe audit path: {name}")
            try:
                self.connection, self._database_fd = open_bound_sqlite(
                    self._directory_fd,
                    self.path.name,
                    timeout=5,
                )
            except OSError as error:
                raise AuditError(f"Refusing unsafe audit path: {self.path.name}") from error
            self.connection.row_factory = sqlite3.Row
            self._configure_size_limits()
            self.connection.executescript(SCHEMA)
            self.connection.commit()
            with self._write_lock():
                self._remove_orphan_images()
                self._prune_locked()
        except Exception as error:
            connection = getattr(self, "connection", None)
            if connection is not None:
                connection.close()
            if self._database_fd >= 0:
                os.close(self._database_fd)
            if self._write_lock_fd >= 0:
                os.close(self._write_lock_fd)
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
        os.close(self._database_fd)
        os.close(self._write_lock_fd)
        os.close(self._lock_fd)
        self._directory.__exit__(None, None, None)
        self._closed = True

    def __enter__(self) -> AuditStore:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def _configure_size_limits(self) -> None:
        page_size = int(self.connection.execute("PRAGMA page_size").fetchone()[0])
        max_pages = max(1, MAX_AUDIT_DB_BYTES // page_size)
        self.connection.execute(f"PRAGMA max_page_count={max_pages}")
        self.connection.execute("PRAGMA wal_autocheckpoint=500")
        self.connection.execute(f"PRAGMA journal_size_limit={MAX_AUDIT_WAL_BYTES}")
        if os.fstat(self._database_fd).st_size > MAX_AUDIT_DB_BYTES:
            raise AuditError("Audit database exceeds its size quota.")

    @contextmanager
    def _write_lock(self):
        fcntl.flock(self._write_lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self._write_lock_fd, fcntl.LOCK_UN)

    def _delete_rows(self, rows: list[sqlite3.Row]) -> None:
        if not rows:
            return
        identifiers = [int(row["id"]) for row in rows]
        for offset in range(0, len(identifiers), 500):
            chunk = identifiers[offset:offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            self.connection.execute(
                f"DELETE FROM requests WHERE id IN ({placeholders})",
                chunk,
            )
        self.connection.commit()
        for row in rows:
            name = str(row["image_file"] or "")
            if not IMAGE_NAME.fullmatch(name):
                continue
            try:
                os.unlink(name, dir_fd=self._directory_fd)
            except FileNotFoundError:
                pass

    def _prune_locked(
        self,
        *,
        incoming_content_bytes: int = 0,
        incoming_response_bytes: int = 0,
        additional_rows: int = 0,
        protected_id: int = 0,
    ) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=AUDIT_RETENTION_DAYS)
        ).isoformat(timespec="seconds")
        expired = self.connection.execute(
            """
            SELECT id, image_file, image_bytes, response_bytes FROM requests
            WHERE requested_at < ? AND id != ? ORDER BY id
            """,
            (cutoff, int(protected_id)),
        ).fetchall()
        self._delete_rows(list(expired))

        rows = self.connection.execute(
            """
            SELECT id, image_file, image_bytes, response_bytes FROM requests
            WHERE id != ? ORDER BY id
            """,
            (int(protected_id),),
        ).fetchall()
        protected = self.connection.execute(
            "SELECT image_bytes, response_bytes FROM requests WHERE id=?",
            (int(protected_id),),
        ).fetchone() if protected_id else None
        protected_content = (
            int(protected["image_bytes"]) + int(protected["response_bytes"])
            if protected is not None else 0
        )
        protected_response = int(protected["response_bytes"]) if protected is not None else 0
        total_content = protected_content + sum(
            int(row["image_bytes"]) + int(row["response_bytes"]) for row in rows
        )
        total_response = protected_response + sum(int(row["response_bytes"]) for row in rows)
        total_rows = len(rows) + (1 if protected is not None else 0)
        remove: list[sqlite3.Row] = []
        for row in rows:
            over_rows = total_rows + additional_rows > MAX_AUDIT_ROWS
            over_content = (
                total_content + incoming_content_bytes > MAX_AUDIT_CONTENT_BYTES
            )
            over_responses = (
                total_response + incoming_response_bytes > MAX_AUDIT_RESPONSE_BYTES
            )
            if not (over_rows or over_content or over_responses):
                break
            remove.append(row)
            total_rows -= 1
            total_content -= int(row["image_bytes"]) + int(row["response_bytes"])
            total_response -= int(row["response_bytes"])
        self._delete_rows(remove)
        if (
            total_rows + additional_rows > MAX_AUDIT_ROWS
            or total_content + incoming_content_bytes > MAX_AUDIT_CONTENT_BYTES
            or total_response + incoming_response_bytes > MAX_AUDIT_RESPONSE_BYTES
        ):
            raise AuditError("The request exceeds the audit archive quota.")
        return len(expired) + len(remove)

    def prune(self) -> int:
        with self._write_lock():
            return self._prune_locked()

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
        with self._write_lock():
            try:
                self._prune_locked(
                    incoming_content_bytes=len(image),
                    additional_rows=1,
                )
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
                self.connection.execute(
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
                if isinstance(error, AuditError):
                    raise
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
        with self._write_lock():
            try:
                current = self.connection.execute(
                    "SELECT response_bytes FROM requests WHERE id=?",
                    (int(record_id),),
                ).fetchone()
                if current is None:
                    raise AuditError("Audit record was not found.")
                previous_response = int(current["response_bytes"])
                self._prune_locked(
                    incoming_content_bytes=len(raw_response) - previous_response,
                    incoming_response_bytes=len(raw_response) - previous_response,
                    protected_id=record_id,
                )
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
        self.prune()
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
            "retention_days": AUDIT_RETENTION_DAYS,
            "max_records": MAX_AUDIT_ROWS,
            "max_content_bytes": MAX_AUDIT_CONTENT_BYTES,
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
