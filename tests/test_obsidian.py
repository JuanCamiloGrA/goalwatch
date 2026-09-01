import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goalwatch.config import load_config, set_manual_goal
from goalwatch.obsidian import ObsidianError, disable_integration, enable_integration, install_plugin


class ObsidianIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / "config"),
                "XDG_STATE_HOME": str(self.home / "state"),
                "XDG_RUNTIME_DIR": str(self.home / "runtime"),
            },
        )
        self.environment.start()
        self.source = self.home / "companion"
        self.source.mkdir()
        (self.source / "main.js").write_text("module.exports = {};\n", encoding="utf-8")
        (self.source / "manifest.json").write_text(
            json.dumps({"id": "goalwatch"}), encoding="utf-8"
        )

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def vault(self) -> Path:
        vault = self.home / "Vault"
        (vault / ".obsidian").mkdir(parents=True)
        return vault

    def register(self, vault: Path) -> None:
        registry = self.home / ".config" / "obsidian" / "obsidian.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps({"vaults": {"id": {"path": str(vault), "open": True, "ts": 10}}}),
            encoding="utf-8",
        )

    @patch("goalwatch.obsidian.obsidian_installed", return_value=False)
    @patch("goalwatch.obsidian.obsidian_running", return_value=False)
    def test_enable_without_obsidian_keeps_manual_mode(self, _running, _installed):
        set_manual_goal("Keep working manually", "Codex")
        vault = self.vault()
        self.register(vault)
        with self.assertRaisesRegex(ObsidianError, "not installed"):
            enable_integration(source=self.source)
        config = load_config()
        self.assertEqual(config["goal_source"], "manual")
        self.assertFalse(config["obsidian_enabled"])
        self.assertEqual(config["manual_goal"], "Keep working manually")

    @patch("goalwatch.obsidian.obsidian_installed", return_value=True)
    @patch("goalwatch.obsidian.obsidian_running", return_value=False)
    def test_enable_and_disable_are_one_step_and_preserve_other_plugins(
        self, _running, _installed
    ):
        vault = self.vault()
        self.register(vault)
        registry = vault / ".obsidian" / "community-plugins.json"
        registry.write_text(json.dumps(["other-plugin"]), encoding="utf-8")

        enabled = enable_integration(source=self.source)
        self.assertTrue(enabled["ok"])
        self.assertTrue(enabled["connected"])
        self.assertTrue((vault / ".obsidian" / "plugins" / "goalwatch" / "main.js").is_file())
        self.assertEqual(json.loads(registry.read_text(encoding="utf-8")), ["other-plugin", "goalwatch"])
        config = load_config()
        self.assertTrue(config["obsidian_enabled"])
        self.assertEqual(config["goal_source"], "obsidian")

        disabled = disable_integration()
        self.assertTrue(disabled["ok"])
        self.assertFalse(load_config()["obsidian_enabled"])
        self.assertEqual(load_config()["goal_source"], "manual")
        self.assertFalse((vault / ".obsidian" / "plugins" / "goalwatch").exists())
        self.assertEqual(json.loads(registry.read_text(encoding="utf-8")), ["other-plugin"])

        again = disable_integration()
        self.assertTrue(again["ok"])
        self.assertEqual(again["warnings"], [])

    def test_invalid_community_registry_is_never_overwritten(self):
        vault = self.vault()
        registry = vault / ".obsidian" / "community-plugins.json"
        registry.write_text("not valid json", encoding="utf-8")
        with self.assertRaisesRegex(ObsidianError, "without risking other plugins"):
            install_plugin(self.source, vault)
        self.assertEqual(registry.read_text(encoding="utf-8"), "not valid json")
        self.assertFalse((vault / ".obsidian" / "plugins" / "goalwatch").exists())

    def test_symlinked_community_registry_is_never_replaced(self):
        vault = self.vault()
        outside = self.home / "outside.json"
        outside.write_text(json.dumps(["other-plugin"]), encoding="utf-8")
        registry = vault / ".obsidian" / "community-plugins.json"
        registry.symlink_to(outside)
        with self.assertRaisesRegex(ObsidianError, "symlinked plugin registry"):
            install_plugin(self.source, vault)
        self.assertEqual(json.loads(outside.read_text(encoding="utf-8")), ["other-plugin"])

    def test_stale_registered_vault_is_ignored(self):
        stale = self.home / "Missing"
        self.register(stale)
        with patch("goalwatch.obsidian.obsidian_installed", return_value=True), patch(
            "goalwatch.obsidian.obsidian_running", return_value=False
        ):
            with self.assertRaisesRegex(ObsidianError, "No local Obsidian vault"):
                enable_integration(source=self.source)


if __name__ == "__main__":
    unittest.main()
