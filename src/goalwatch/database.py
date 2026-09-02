from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .secureio import atomic_write_bytes_at, read_bytes_at


SQLITE_HEADER = b"SQLite format 3\x00"
LEGACY_AUXILIARY_SUFFIXES = ("-wal", "-shm", "-journal")


class AtomicSQLite:
    """SQLite in memory with one descriptor-safe, atomically replaced snapshot."""

    def __init__(self, directory_fd: int, name: str, *, max_bytes: int) -> None:
        if not name or name in {".", ".."} or Path(name).name != name:
            raise OSError("Unsafe SQLite snapshot name.")
        self.directory_fd = directory_fd
        self.name = name
        self.max_bytes = max_bytes
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

    def _configure_limits(self, connection: sqlite3.Connection) -> None:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        if page_size <= 0 or page_size > self.max_bytes:
            raise OSError("SQLite snapshot has an invalid page size.")
        max_pages = max(1, self.max_bytes // page_size)
        connection.execute(f"PRAGMA max_page_count={max_pages}")

    def _reject_auxiliary_paths(self) -> None:
        for suffix in LEGACY_AUXILIARY_SUFFIXES:
            try:
                os.stat(
                    f"{self.name}{suffix}",
                    dir_fd=self.directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            raise OSError(
                f"Refusing legacy SQLite auxiliary path: {self.name}{suffix}. "
                "Stop every older GoalWatch process and retry."
            )

    @staticmethod
    def _normalize_legacy_header(data: bytes) -> bytes:
        if len(data) < 100 or not data.startswith(SQLITE_HEADER):
            raise OSError("SQLite snapshot has an invalid header.")
        read_version, write_version = data[18], data[19]
        if read_version not in {1, 2} or write_version not in {1, 2}:
            raise OSError("SQLite snapshot has unsupported journal metadata.")
        if read_version == 1 and write_version == 1:
            return data
        normalized = bytearray(data)
        normalized[18] = 1
        normalized[19] = 1
        return bytes(normalized)

    def load(self) -> bool:
        self._reject_auxiliary_paths()
        try:
            data = read_bytes_at(
                self.directory_fd,
                self.name,
                limit=self.max_bytes,
            )
        except FileNotFoundError:
            data = b""
        replacement = sqlite3.connect(":memory:")
        replacement.row_factory = sqlite3.Row
        try:
            if data:
                replacement.deserialize(self._normalize_legacy_header(data))
                result = replacement.execute("PRAGMA quick_check").fetchone()
                if result is None or result[0] != "ok":
                    raise OSError("SQLite snapshot failed its integrity check.")
            self._configure_limits(replacement)
            replacement.execute("PRAGMA foreign_keys=ON")
        except BaseException:
            replacement.close()
            raise
        self.connection.close()
        self.connection = replacement
        return bool(data)

    def save(self) -> None:
        self.connection.commit()
        data = self.connection.serialize()
        if (
            not data.startswith(SQLITE_HEADER)
            or len(data) > self.max_bytes
            or data[18:20] != b"\x01\x01"
        ):
            raise OSError("SQLite snapshot exceeds its size quota.")
        self._reject_auxiliary_paths()
        atomic_write_bytes_at(self.directory_fd, self.name, data)

    def close(self) -> None:
        self.connection.close()
