import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goalwatch.database import AtomicSQLite, LEGACY_AUXILIARY_SUFFIXES


class AtomicDatabaseTests(unittest.TestCase):
    def open_directory(self, root: Path) -> int:
        return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def create_snapshot(self, directory_fd: int, name: str = "data.sqlite3") -> None:
        database = AtomicSQLite(directory_fd, name, max_bytes=1024 * 1024)
        try:
            database.load()
            database.connection.execute("CREATE TABLE proof(value TEXT)")
            database.connection.execute("INSERT INTO proof VALUES('bound')")
            database.save()
        finally:
            database.close()

    def test_every_sqlite_connection_is_memory_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            directory_fd = self.open_directory(root)
            original_connect = sqlite3.connect
            targets: list[object] = []

            def observe(target, *arguments, **keywords):
                targets.append(target)
                return original_connect(target, *arguments, **keywords)

            try:
                with patch("goalwatch.database.sqlite3.connect", side_effect=observe):
                    self.create_snapshot(directory_fd)
                    database = AtomicSQLite(
                        directory_fd, "data.sqlite3", max_bytes=1024 * 1024
                    )
                    database.load()
                    self.assertEqual(
                        database.connection.execute("SELECT value FROM proof").fetchone()[0],
                        "bound",
                    )
                    database.close()
            finally:
                os.close(directory_fd)
        self.assertTrue(targets)
        self.assertEqual(set(targets), {":memory:"})

    def test_symlinked_and_hardlinked_snapshots_are_refused(self):
        for link_kind in ("symlink", "hardlink"):
            with self.subTest(link_kind=link_kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outside = root / "outside"
                outside.write_bytes(b"do not touch")
                target = root / "data.sqlite3"
                if link_kind == "symlink":
                    target.symlink_to(outside)
                else:
                    os.link(outside, target)
                directory_fd = self.open_directory(root)
                try:
                    database = AtomicSQLite(
                        directory_fd, target.name, max_bytes=1024 * 1024
                    )
                    with self.assertRaises(OSError):
                        database.load()
                    database.close()
                finally:
                    os.close(directory_fd)
                self.assertEqual(outside.read_bytes(), b"do not touch")

    def test_legacy_auxiliary_paths_are_never_opened_or_modified(self):
        for suffix in LEGACY_AUXILIARY_SUFFIXES:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outside = root / "outside"
                outside.write_bytes(b"do not touch")
                directory_fd = self.open_directory(root)
                try:
                    self.create_snapshot(directory_fd)
                    os.link(outside, root / f"data.sqlite3{suffix}")
                    database = AtomicSQLite(
                        directory_fd, "data.sqlite3", max_bytes=1024 * 1024
                    )
                    with self.assertRaisesRegex(OSError, "auxiliary path"):
                        database.load()
                    database.close()
                finally:
                    os.close(directory_fd)
                self.assertEqual(outside.read_bytes(), b"do not touch")

    def test_wal_and_shm_replacement_after_load_are_never_opened_or_modified(self):
        for suffix in ("-wal", "-shm"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outside = root / "outside"
                outside.write_bytes(b"do not touch")
                directory_fd = self.open_directory(root)
                try:
                    self.create_snapshot(directory_fd)
                    database = AtomicSQLite(
                        directory_fd, "data.sqlite3", max_bytes=1024 * 1024
                    )
                    database.load()
                    database.connection.execute("INSERT INTO proof VALUES('new')")
                    os.link(outside, root / f"data.sqlite3{suffix}")
                    with self.assertRaisesRegex(OSError, "auxiliary path"):
                        database.save()
                    database.close()
                finally:
                    os.close(directory_fd)
                self.assertEqual(outside.read_bytes(), b"do not touch")

    def test_path_replacement_before_save_cannot_modify_the_replacement_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_bytes(b"do not touch")
            directory_fd = self.open_directory(root)
            try:
                self.create_snapshot(directory_fd)
                database = AtomicSQLite(
                    directory_fd, "data.sqlite3", max_bytes=1024 * 1024
                )
                database.load()
                database.connection.execute("INSERT INTO proof VALUES('new')")
                os.unlink(root / "data.sqlite3")
                os.link(outside, root / "data.sqlite3")
                database.save()
                database.close()
            finally:
                os.close(directory_fd)
            self.assertEqual(outside.read_bytes(), b"do not touch")
            connection = sqlite3.connect(root / "data.sqlite3")
            try:
                self.assertEqual(
                    connection.execute("SELECT value FROM proof ORDER BY rowid").fetchall(),
                    [("bound",), ("new",)],
                )
            finally:
                connection.close()

    def test_clean_legacy_wal_header_is_normalized_without_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            directory_fd = self.open_directory(root)
            try:
                self.create_snapshot(directory_fd)
                data = bytearray((root / "data.sqlite3").read_bytes())
                data[18:20] = b"\x02\x02"
                (root / "data.sqlite3").write_bytes(data)
                database = AtomicSQLite(
                    directory_fd, "data.sqlite3", max_bytes=1024 * 1024
                )
                database.load()
                self.assertEqual(
                    database.connection.execute("SELECT value FROM proof").fetchone()[0],
                    "bound",
                )
                database.save()
                database.close()
            finally:
                os.close(directory_fd)
            snapshot = (root / "data.sqlite3").read_bytes()
            self.assertEqual(snapshot[18:20], b"\x01\x01")
            self.assertFalse(
                any((root / f"data.sqlite3{suffix}").exists() for suffix in LEGACY_AUXILIARY_SUFFIXES)
            )


if __name__ == "__main__":
    unittest.main()
