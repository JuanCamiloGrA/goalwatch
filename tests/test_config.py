import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goalwatch.config import ConfigError, load_config, set_daily_file, set_manual_file, set_value


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.temporary.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def test_defaults(self):
        config = load_config()
        self.assertEqual(config["interval_minutes"], 5)
        self.assertEqual(config["model"], "gemini-flash-lite-latest")

    def test_interval_validation_and_permissions(self):
        config = set_value("interval_minutes", "7")
        self.assertEqual(config["interval_minutes"], 7)
        path = Path(self.temporary.name) / "goalwatch" / "config.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ConfigError):
            set_value("interval_minutes", "0")

    def test_manual_override_survives_same_daily_then_expires(self):
        vault = Path(self.temporary.name) / "vault"
        vault.mkdir()
        set_daily_file(str(vault), "daily/2026-09-01.md", "2026-09-01")
        manual = str(vault / "project.md")
        set_manual_file(manual, "2026-09-01")
        same = set_daily_file(str(vault), "daily/2026-09-01.md", "2026-09-01")
        self.assertEqual(same["markdown_file"], manual)
        next_day = set_daily_file(str(vault), "daily/2026-09-02.md", "2026-09-02")
        self.assertEqual(next_day["markdown_source"], "daily")
        self.assertTrue(next_day["markdown_file"].endswith("daily/2026-09-02.md"))

    def test_daily_path_cannot_escape_vault(self):
        with self.assertRaises(ConfigError):
            set_daily_file(self.temporary.name, "../outside.md", "2026-09-01")

    def test_daily_path_cannot_escape_through_parent_symlink(self):
        vault = Path(self.temporary.name) / "vault"
        outside = Path(self.temporary.name) / "outside"
        vault.mkdir()
        outside.mkdir()
        (vault / "linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ConfigError):
            set_daily_file(str(vault), "linked/goal.md", "2026-09-01")


if __name__ == "__main__":
    unittest.main()
