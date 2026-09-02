from __future__ import annotations

import fcntl
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


def _read_validated_descriptor(
    descriptor: int,
    *,
    limit: int,
    require_owner: bool,
    require_single_link: bool,
) -> bytes:
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or (require_owner and info.st_uid != os.getuid())
        or (require_single_link and info.st_nlink != 1)
        or info.st_size < 0
        or info.st_size > limit
    ):
        raise OSError("Refusing an unsafe or oversized file.")
    current_flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
    fcntl.fcntl(descriptor, fcntl.F_SETFL, current_flags & ~os.O_NONBLOCK)
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > limit:
        raise OSError("Refusing an oversized file.")
    return content


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


def read_bytes_at(
    directory: int,
    name: str,
    *,
    limit: int,
    require_owner: bool = True,
    require_single_link: bool = True,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(_file_name(name), flags, dir_fd=directory)
    try:
        return _read_validated_descriptor(
            descriptor,
            limit=limit,
            require_owner=require_owner,
            require_single_link=require_single_link,
        )
    finally:
        os.close(descriptor)


def read_bytes_path(
    path: Path,
    *,
    limit: int,
    require_owner: bool = True,
    require_single_link: bool = True,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        return _read_validated_descriptor(
            descriptor,
            limit=limit,
            require_owner=require_owner,
            require_single_link=require_single_link,
        )
    finally:
        os.close(descriptor)


def read_text_at(
    directory: int,
    name: str,
    *,
    limit: int,
    require_owner: bool = True,
    require_single_link: bool = True,
) -> str:
    return read_bytes_at(
        directory,
        name,
        limit=limit,
        require_owner=require_owner,
        require_single_link=require_single_link,
    ).decode("utf-8")


def atomic_write_bytes_at(directory: int, name: str, content: bytes, *, mode: int = 0o600) -> None:
    target = _file_name(name)
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
            handle.write(content)
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


def atomic_write_text_at(directory: int, name: str, content: str, *, mode: int = 0o600) -> None:
    atomic_write_bytes_at(directory, name, content.encode("utf-8"), mode=mode)


def open_lock_at(directory: int, name: str) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(_file_name(name), flags, 0o600, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OSError("Refusing an unsafe lock file.")
        current_flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        fcntl.fcntl(descriptor, fcntl.F_SETFL, current_flags & ~os.O_NONBLOCK)
        os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
