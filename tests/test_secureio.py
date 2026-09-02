import os
import tempfile
import time
import unittest
from pathlib import Path

from goalwatch.secureio import (
    atomic_write_bytes_at,
    open_lock_at,
    read_bytes_at,
    read_bytes_path,
)


class SecureIoTests(unittest.TestCase):
    def test_fifo_reads_and_lock_opens_fail_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "untrusted"
            os.mkfifo(fifo)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                started = time.monotonic()
                with self.assertRaises(OSError):
                    read_bytes_at(directory_fd, fifo.name, limit=1024)
                self.assertLess(time.monotonic() - started, 0.5)

                started = time.monotonic()
                with self.assertRaises(OSError):
                    read_bytes_path(fifo, limit=1024)
                self.assertLess(time.monotonic() - started, 0.5)

                started = time.monotonic()
                with self.assertRaises(OSError):
                    open_lock_at(directory_fd, fifo.name)
                self.assertLess(time.monotonic() - started, 0.5)
            finally:
                os.close(directory_fd)

    def test_hardlinked_inputs_and_locks_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_bytes(b"do not touch")
            outside.chmod(0o644)
            linked_input = root / "input"
            linked_lock = root / "lock"
            os.link(outside, linked_input)
            os.link(outside, linked_lock)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                with self.assertRaises(OSError):
                    read_bytes_at(directory_fd, linked_input.name, limit=1024)
                with self.assertRaises(OSError):
                    open_lock_at(directory_fd, linked_lock.name)
            finally:
                os.close(directory_fd)
            self.assertEqual(outside.read_bytes(), b"do not touch")
            self.assertEqual(outside.stat().st_mode & 0o777, 0o644)

    def test_atomic_write_replaces_a_hardlink_without_modifying_its_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_bytes(b"do not touch")
            target = root / "target"
            os.link(outside, target)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                atomic_write_bytes_at(directory_fd, target.name, b"replacement")
            finally:
                os.close(directory_fd)
            self.assertEqual(outside.read_bytes(), b"do not touch")
            self.assertEqual(target.read_bytes(), b"replacement")
            self.assertNotEqual(outside.stat().st_ino, target.stat().st_ino)


if __name__ == "__main__":
    unittest.main()
