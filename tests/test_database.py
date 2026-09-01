import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goalwatch.database import open_bound_sqlite


class BoundDatabaseTests(unittest.TestCase):
    def test_path_replacement_during_open_is_detected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_bytes(b"do not touch")
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            original_connect = sqlite3.connect

            def replace_then_connect(*arguments, **keywords):
                os.rename(
                    "data.sqlite3",
                    "opened-inode.sqlite3",
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                os.symlink(outside, "data.sqlite3", dir_fd=directory_fd)
                return original_connect(*arguments, **keywords)

            try:
                with patch("goalwatch.database.sqlite3.connect", side_effect=replace_then_connect):
                    with self.assertRaisesRegex(OSError, "path changed"):
                        open_bound_sqlite(directory_fd, "data.sqlite3")
            finally:
                os.close(directory_fd)
            self.assertEqual(outside.read_bytes(), b"do not touch")
            self.assertTrue((root / "opened-inode.sqlite3").is_file())

    def test_connection_is_bound_to_the_validated_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                connection, database_fd = open_bound_sqlite(directory_fd, "data.sqlite3")
                connection.execute("CREATE TABLE proof(value TEXT)")
                connection.execute("INSERT INTO proof VALUES('bound')")
                connection.commit()
                inode = os.fstat(database_fd).st_ino
                connection.close()
                os.close(database_fd)
            finally:
                os.close(directory_fd)
            self.assertEqual(inode, (root / "data.sqlite3").stat().st_ino)


if __name__ == "__main__":
    unittest.main()
