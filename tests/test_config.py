import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goalwatch.config import (
    ConfigError,
    load_config,
    set_daily_file,
    set_manual_file,
    set_manual_goal,
    set_obsidian_integration,
    set_value,
)


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
        self.assertEqual(config["goal_source"], "manual")
        self.assertFalse(config["obsidian_enabled"])
        self.assertEqual(config["manual_goal"], "")

    def test_legacy_markdown_install_migrates_without_losing_source(self):
        path = Path(self.temporary.name) / "goalwatch" / "config.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps({"version": 1, "markdown_file": "/vault/daily.md", "markdown_source": "daily"}),
            encoding="utf-8",
        )
        config = load_config()
        self.assertEqual(config["goal_source"], "obsidian")
        self.assertTrue(config["obsidian_enabled"])
        self.assertEqual(config["markdown_file"], "/vault/daily.md")

    def test_source_and_integration_cannot_normalize_to_conflicting_states(self):
        path = Path(self.temporary.name) / "goalwatch" / "config.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps({"version": 2, "goal_source": "obsidian", "obsidian_enabled": False}),
            encoding="utf-8",
        )
        self.assertEqual(load_config()["goal_source"], "manual")

    def test_fifo_config_falls_back_without_waiting_for_a_writer(self):
        path = Path(self.temporary.name) / "goalwatch" / "config.json"
        path.parent.mkdir()
        os.mkfifo(path)
        self.assertEqual(load_config()["manual_goal"], "")

    def test_manual_goal_is_private_and_bounded(self):
        config = set_manual_goal(" Ship the release ", " Codex, Browser ")
        self.assertEqual(config["manual_goal"], "Ship the release")
        self.assertEqual(config["manual_tools"], "Codex, Browser")
        path = Path(self.temporary.name) / "goalwatch" / "config.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ConfigError):
            set_manual_goal("x" * 2001, "Codex")

    def test_disabling_obsidian_selects_manual_goal_without_erasing_it(self):
        vault = Path(self.temporary.name) / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        set_manual_goal("Fallback goal", "Codex")
        set_obsidian_integration(True, str(vault))
        config = set_obsidian_integration(False)
        self.assertEqual(config["goal_source"], "manual")
        self.assertFalse(config["obsidian_enabled"])
        self.assertEqual(config["manual_goal"], "Fallback goal")

    def test_interval_validation_and_permissions(self):
        config = set_value("interval_minutes", "7")
        self.assertEqual(config["interval_minutes"], 7)
        path = Path(self.temporary.name) / "goalwatch" / "config.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ConfigError):
            set_value("interval_minutes", "0")

    def test_config_symlink_is_replaced_without_touching_its_target(self):
        app = Path(self.temporary.name) / "goalwatch"
        app.mkdir()
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text('{"keep":true}\n', encoding="utf-8")
        (app / "config.json").symlink_to(outside)
        config = set_value("interval_minutes", "9")
        self.assertEqual(config["interval_minutes"], 9)
        self.assertEqual(outside.read_text(encoding="utf-8"), '{"keep":true}\n')
        self.assertFalse((app / "config.json").is_symlink())

    def test_symlinked_private_config_directory_is_refused(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (Path(self.temporary.name) / "goalwatch").symlink_to(outside, target_is_directory=True)
        self.assertEqual(load_config()["manual_goal"], "")
        with self.assertRaises(OSError):
            set_value("interval_minutes", "9")
        self.assertEqual(list(outside.iterdir()), [])

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
