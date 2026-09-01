from __future__ import annotations

import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _file_name(name: str) -> str:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise OSError("Unsafe file name.")
    return name


@contextmanager
def directory_fd(path: Path, *, create: bool = False, private: bool = False) -> Iterator[int]:
    if create:
        path.mkdir(mode=0o700 if private else 0o755, parents=True, exist_ok=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise OSError("Expected a directory.")
        if private:
            if info.st_uid != os.getuid():
                raise OSError("Private directory is not owned by the current user.")
            os.fchmod(descriptor, 0o700)
        yield descriptor
    finally:
        os.close(descriptor)


def read_text_at(directory: int, name: str, *, limit: int) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(_file_name(name), flags, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise OSError("Refusing an unsafe or oversized file.")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read(limit + 1)
        if len(content) > limit:
            raise OSError("Refusing an oversized file.")
        return content.decode("utf-8")
    finally:
        os.close(descriptor)


def atomic_write_text_at(directory: int, name: str, content: str, *, mode: int = 0o600) -> None:
    target = _file_name(name)
    encoded = content.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    temporary = ""
    for _attempt in range(20):
        temporary = f".{target}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(temporary, flags, mode, dir_fd=directory)
            break
        except FileExistsError:
            continue
    if descriptor < 0:
        raise OSError("Could not allocate a secure temporary file.")
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)


def open_lock_at(directory: int, name: str) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(_file_name(name), flags, 0o600, dir_fd=directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("Refusing an unsafe lock file.")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
