from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path


def open_bound_sqlite(
    directory_fd: int,
    name: str,
    *,
    timeout: float = 5,
) -> tuple[sqlite3.Connection, int]:
    """Open SQLite through a previously validated descriptor, not a pathname."""
    if not name or name in {".", ".."} or Path(name).name != name:
        raise OSError("Unsafe SQLite database name.")
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    connection: sqlite3.Connection | None = None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("Refusing an unsafe SQLite database file.")
        os.fchmod(descriptor, 0o600)
        connection = sqlite3.connect(
            f"file:/proc/self/fd/{descriptor}?mode=rw",
            uri=True,
            timeout=timeout,
        )
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (
            info.st_dev,
            info.st_ino,
        ):
            raise OSError("SQLite database path changed while it was being opened.")
        return connection, descriptor
    except BaseException:
        if connection is not None:
            connection.close()
        os.close(descriptor)
        raise
