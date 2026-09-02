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

from .database import AtomicSQLite
from .paths import audit_dir, audit_file
from .secureio import (
    atomic_write_bytes_at,
    directory_fd,
    open_lock_at,
    read_bytes_at,
)


IMAGE_NAME = re.compile(r"^request-[0-9]{8}\.jpg$")
RESPONSE_NAME = re.compile(r"^response-[0-9]{8}\.bin$")
OUTCOMES = {"pending", "on_goal", "off_goal", "error"}
MAX_QUERY_CHARS = 200
MAX_PAGE_SIZE = 100
MAX_RESPONSE_SEARCH_CHARS = 2_000
MAX_RAW_RESPONSE_BYTES = 512 * 1024
MAX_STORED_IMAGE_BYTES = 8 * 1024 * 1024
AUDIT_RETENTION_DAYS = 7
MAX_AUDIT_ROWS = 2_000
MAX_AUDIT_CONTENT_BYTES = 512 * 1024 * 1024
MAX_AUDIT_RESPONSE_BYTES = 224 * 1024 * 1024
MAX_AUDIT_DB_BYTES = 256 * 1024 * 1024
MAX_AUDIT_DIRECTORY_ENTRIES = 10_000

SCHEMA = """
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
  response_file TEXT NOT NULL DEFAULT '',
  response_search TEXT NOT NULL DEFAULT '',
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
        self._data_lock_fd = -1
        self.database: AtomicSQLite | None = None
        try:
            self._lock_fd = open_lock_at(self._directory_fd, ".audit.lock")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            self._data_lock_fd = open_lock_at(self._directory_fd, ".audit.data.lock")
            self.database = AtomicSQLite(
                self._directory_fd,
                self.path.name,
                max_bytes=MAX_AUDIT_DB_BYTES,
            )
            with self._data_lock():
                self._reload_locked()
                _count, attachments = self._prune_locked()
                self._save_locked()
                self._unlink_attachments(attachments)
                self._remove_orphan_files_locked()
        except Exception as error:
            if self.database is not None:
                self.database.close()
            if self._data_lock_fd >= 0:
                os.close(self._data_lock_fd)
            if self._lock_fd >= 0:
                os.close(self._lock_fd)
            self._directory.__exit__(None, None, None)
            if isinstance(error, AuditError):
                raise
            raise AuditError("Could not open the private audit archive.") from error

    @property
    def connection(self) -> sqlite3.Connection:
        if self.database is None:
            raise AuditError("Audit archive is closed.")
        return self.database.connection

    def close(self) -> None:
        if self._closed:
            return
        if self.database is not None:
            self.database.close()
        os.close(self._data_lock_fd)
        os.close(self._lock_fd)
        self._directory.__exit__(None, None, None)
        self._closed = True

    def __enter__(self) -> AuditStore:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    @contextmanager
    def _data_lock(self):
        fcntl.flock(self._data_lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self._data_lock_fd, fcntl.LOCK_UN)

    def _reload_locked(self) -> None:
        if self.database is None:
            raise AuditError("Audit archive is closed.")
        self.database.load()
        self.connection.executescript(SCHEMA)
        columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(requests)")
        }
        if "response_file" not in columns:
            self.connection.execute(
                "ALTER TABLE requests ADD COLUMN response_file TEXT NOT NULL DEFAULT ''"
            )
        if "response_search" not in columns:
            self.connection.execute(
                "ALTER TABLE requests ADD COLUMN response_search TEXT NOT NULL DEFAULT ''"
            )

    def _save_locked(self) -> None:
        if self.database is None:
            raise AuditError("Audit archive is closed.")
        self.database.save()

    @staticmethod
    def _search_text(raw: bytes) -> str:
        return raw.decode("utf-8", errors="replace")[:MAX_RESPONSE_SEARCH_CHARS]

    @staticmethod
    def _attachment_names(row: sqlite3.Row) -> tuple[str, str]:
        return str(row["image_file"] or ""), str(row["response_file"] or "")

    def _delete_rows_locked(self, rows: list[sqlite3.Row]) -> list[tuple[str, str]]:
        if not rows:
            return []
        identifiers = [int(row["id"]) for row in rows]
        for offset in range(0, len(identifiers), 500):
            chunk = identifiers[offset:offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            self.connection.execute(
                f"DELETE FROM requests WHERE id IN ({placeholders})",
                chunk,
            )
        return [self._attachment_names(row) for row in rows]

    def _unlink_attachments(self, attachments: list[tuple[str, str]]) -> list[str]:
        failures: list[str] = []
        for image_name, response_name in attachments:
            for name, pattern in (
                (image_name, IMAGE_NAME),
                (response_name, RESPONSE_NAME),
            ):
                if not pattern.fullmatch(name):
                    continue
                try:
                    os.unlink(name, dir_fd=self._directory_fd)
                except FileNotFoundError:
                    pass
                except OSError:
                    failures.append(name)
        return failures

    def _prune_locked(
        self,
        *,
        incoming_content_bytes: int = 0,
        incoming_response_bytes: int = 0,
        additional_rows: int = 0,
        protected_id: int = 0,
    ) -> tuple[int, list[tuple[str, str]]]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=AUDIT_RETENTION_DAYS)
        ).isoformat(timespec="seconds")
        expired = self.connection.execute(
            """
            SELECT id, image_file, response_file, image_bytes, response_bytes
            FROM requests WHERE requested_at < ? AND id != ? ORDER BY id
            """,
            (cutoff, int(protected_id)),
        ).fetchall()
        attachments = self._delete_rows_locked(list(expired))

        rows = self.connection.execute(
            """
            SELECT id, image_file, response_file, image_bytes, response_bytes, outcome
            FROM requests WHERE id != ? ORDER BY id
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
        protected_response = int(protected["response_bytes"]) if protected else 0
        total_content = protected_content + sum(
            int(row["image_bytes"]) + int(row["response_bytes"]) for row in rows
        )
        total_response = protected_response + sum(int(row["response_bytes"]) for row in rows)
        total_rows = len(rows) + (1 if protected is not None else 0)
        remove: list[sqlite3.Row] = []
        for row in (candidate for candidate in rows if candidate["outcome"] != "pending"):
            if not (
                total_rows + additional_rows > MAX_AUDIT_ROWS
                or total_content + incoming_content_bytes > MAX_AUDIT_CONTENT_BYTES
                or total_response + incoming_response_bytes > MAX_AUDIT_RESPONSE_BYTES
            ):
                break
            remove.append(row)
            total_rows -= 1
            total_content -= int(row["image_bytes"]) + int(row["response_bytes"])
            total_response -= int(row["response_bytes"])
        attachments.extend(self._delete_rows_locked(remove))
        if (
            total_rows + additional_rows > MAX_AUDIT_ROWS
            or total_content + incoming_content_bytes > MAX_AUDIT_CONTENT_BYTES
            or total_response + incoming_response_bytes > MAX_AUDIT_RESPONSE_BYTES
        ):
            raise AuditError("The request exceeds the audit archive quota.")
        return len(expired) + len(remove), attachments

    def prune(self) -> int:
        with self._data_lock():
            try:
                self._reload_locked()
                count, attachments = self._prune_locked()
                self._save_locked()
                self._unlink_attachments(attachments)
                self._remove_orphan_files_locked()
                return count
            except (OSError, sqlite3.Error, AuditError) as error:
                if isinstance(error, AuditError):
                    raise
                raise AuditError("Could not prune the audit archive.") from error

    def _remove_orphan_files_locked(self) -> None:
        referenced = {
            str(value)
            for row in self.connection.execute(
                "SELECT image_file, response_file FROM requests"
            ).fetchall()
            for value in row
            if value
        }
        directory = f"/proc/self/fd/{self._directory_fd}"
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > MAX_AUDIT_DIRECTORY_ENTRIES:
                    raise AuditError("The audit directory exceeds its entry quota.")
                if (
                    (IMAGE_NAME.fullmatch(entry.name) or RESPONSE_NAME.fullmatch(entry.name))
                    and entry.name not in referenced
                ):
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
        if not image or len(image) > MAX_STORED_IMAGE_BYTES:
            raise AuditError("The screenshot exceeds the audit limit.")
        image_name = ""
        with self._data_lock():
            attachments: list[tuple[str, str]] = []
            try:
                self._reload_locked()
                _count, attachments = self._prune_locked(
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
                    (utc_now(), model, endpoint, goal, tools, "", "", len(image), image_digest),
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
                self._save_locked()
                self._unlink_attachments(attachments)
                return record_id
            except Exception as error:
                if image_name:
                    try:
                        os.unlink(image_name, dir_fd=self._directory_fd)
                    except FileNotFoundError:
                        pass
                if isinstance(error, AuditError):
                    raise
                raise AuditError("Could not persist the request audit record.") from error

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
        if len(raw_response) > MAX_RAW_RESPONSE_BYTES:
            raise AuditError("Raw response exceeds the audit limit.")
        response_name = ""
        with self._data_lock():
            try:
                self._reload_locked()
                current = self.connection.execute(
                    "SELECT outcome, response_bytes FROM requests WHERE id=?",
                    (int(record_id),),
                ).fetchone()
                if current is None:
                    raise AuditError("Audit record was not found.")
                if current["outcome"] != "pending":
                    raise AuditError("Audit record is already complete.")
                _count, attachments = self._prune_locked(
                    incoming_content_bytes=len(raw_response),
                    incoming_response_bytes=len(raw_response),
                    protected_id=record_id,
                )
                if raw_response:
                    response_name = f"response-{int(record_id):08d}.bin"
                    atomic_write_bytes_at(self._directory_fd, response_name, raw_response)
                cursor = self.connection.execute(
                    """
                    UPDATE requests SET
                      completed_at=?, http_status=?, response_headers_json=?,
                      response_body=X'', response_file=?, response_search=?,
                      response_bytes=?, response_sha256=?, response_truncated=?,
                      outcome=?, error_code=?, latency_ms=?, prompt_tokens=?, output_tokens=?
                    WHERE id=? AND outcome='pending'
                    """,
                    (
                        utc_now(),
                        max(0, int(http_status)),
                        json.dumps(response_headers or {}, ensure_ascii=False, sort_keys=True),
                        response_name,
                        self._search_text(raw_response),
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
                self._save_locked()
                self._unlink_attachments(attachments)
            except (OSError, sqlite3.Error, AuditError) as error:
                if response_name:
                    try:
                        os.unlink(response_name, dir_fd=self._directory_fd)
                    except FileNotFoundError:
                        pass
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
        with self._data_lock():
            self._reload_locked()
            count, attachments = self._prune_locked()
            if count:
                self._save_locked()
                self._unlink_attachments(attachments)
            clauses: list[str] = []
            parameters: list[object] = []
            if outcome != "all":
                clauses.append("outcome=?")
                parameters.append(outcome)
            if clean_query:
                clauses.append(
                    "(goal LIKE ? OR tools LIKE ? OR model LIKE ? OR error_code LIKE ? "
                    "OR response_search LIKE ? OR CAST(response_body AS TEXT) LIKE ?)"
                )
                needle = f"%{clean_query}%"
                parameters.extend([needle] * 6)
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
        with self._data_lock():
            self._reload_locked()
            row = self.connection.execute(
                "SELECT * FROM requests WHERE id=?", (int(record_id),)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            legacy = bytes(result.pop("response_body") or b"")
            response_name = str(result.get("response_file") or "")
            raw = legacy
            if RESPONSE_NAME.fullmatch(response_name):
                try:
                    raw = read_bytes_at(
                        self._directory_fd,
                        response_name,
                        limit=MAX_RAW_RESPONSE_BYTES,
                    )
                except OSError as error:
                    raise AuditError("Stored audit response is unavailable or unsafe.") from error
            expected_response = str(result.get("response_sha256") or "")
            if expected_response and hashlib.sha256(raw).hexdigest() != expected_response:
                raise AuditError("Stored audit response failed its integrity check.")
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
                    image = read_bytes_at(
                        self._directory_fd,
                        image_name,
                        limit=MAX_STORED_IMAGE_BYTES,
                    )
                    if hashlib.sha256(image).hexdigest() == str(result["image_sha256"]):
                        info = os.stat(
                            image_name,
                            dir_fd=self._directory_fd,
                            follow_symlinks=False,
                        )
                        if stat.S_ISREG(info.st_mode):
                            image_path = str(self.directory_path.resolve() / image_name)
                except OSError:
                    pass
            result.pop("response_search", None)
            result["image_path"] = image_path
            result["raw_response"] = response
            result["raw_response_encoding"] = encoding
            return result

    def clear(self) -> int:
        if not self.exclusive:
            raise AuditError("Clearing audit data requires an exclusive archive lock.")
        with self._data_lock():
            self._reload_locked()
            rows = self.connection.execute(
                "SELECT id, image_file, response_file FROM requests"
            ).fetchall()
            count = len(rows)
            try:
                self.connection.execute("DELETE FROM requests")
                self._save_locked()
            except (OSError, sqlite3.Error) as error:
                raise AuditError("Could not clear the audit archive.") from error
            failures = self._unlink_attachments(
                [self._attachment_names(row) for row in rows]
            )
            if failures:
                raise AuditError(
                    "The audit index was cleared, but some attachments could not be removed."
                )
            self._remove_orphan_files_locked()
            return count
