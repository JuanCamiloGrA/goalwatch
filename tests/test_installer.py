import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


class InstallerTransactionTests(unittest.TestCase):
    def test_late_shell_failure_restores_every_target_and_active_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            config = root / "config"
            runtime = root / "runtime"
            mocks = root / "bin"
            state = root / "service-state"
            events = root / "service-events"
            for path in (home, data, config, runtime, mocks):
                path.mkdir(parents=True, exist_ok=True)
            state.write_text("active\n", encoding="utf-8")

            def executable(name: str, content: str) -> None:
                path = mocks / name
                path.write_text(content, encoding="utf-8")
                path.chmod(0o755)

            executable(
                "systemctl",
                """#!/usr/bin/env bash
set -eu
case "$*" in
  "--user is-active --quiet goalwatch.service") grep -qx active "$MOCK_SERVICE_STATE" ;;
  "--user stop goalwatch.service") printf 'stop\\n' >>"$MOCK_SERVICE_EVENTS"; printf 'inactive\\n' >"$MOCK_SERVICE_STATE" ;;
  "--user start goalwatch.service") printf 'start\\n' >>"$MOCK_SERVICE_EVENTS"; printf 'active\\n' >"$MOCK_SERVICE_STATE" ;;
  "--user daemon-reload") exit 0 ;;
  *) exit 0 ;;
esac
""",
            )
            executable("systemd-analyze", "#!/usr/bin/env bash\nexit 0\n")
            executable("omarchy", "#!/usr/bin/env bash\nexit 0\n")
            executable(
                "omarchy-shell",
                """#!/usr/bin/env bash
if [[ "$*" == "shell rescanPlugins" ]]; then exit 17; fi
exit 0
""",
            )
            for name in ("grim", "secret-tool"):
                executable(name, "#!/usr/bin/env bash\nexit 0\n")

            app = data / "goalwatch" / "app"
            binary = home / ".local" / "bin" / "goalwatch"
            unit = config / "systemd" / "user" / "goalwatch.service"
            plugin = config / "omarchy" / "plugins" / "com.goalwatch"
            docs = data / "doc" / "goalwatch"
            for target in (app, plugin, docs):
                target.mkdir(parents=True)
                (target / "old-marker").write_text("old", encoding="utf-8")
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/usr/bin/env bash\nprintf 'old\\n'\n", encoding="utf-8")
            binary.chmod(0o755)
            unit.parent.mkdir(parents=True)
            unit.write_text("old unit\n", encoding="utf-8")
            shell = config / "omarchy" / "shell.json"
            shell.parent.mkdir(parents=True, exist_ok=True)
            shell.write_text(
                json.dumps({"bar": {"layout": {"right": [{"id": "com.goalwatch"}]}}}),
                encoding="utf-8",
            )

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "XDG_DATA_HOME": str(data),
                    "XDG_CONFIG_HOME": str(config),
                    "XDG_STATE_HOME": str(root / "state"),
                    "XDG_RUNTIME_DIR": str(runtime),
                    "MOCK_SERVICE_STATE": str(state),
                    "MOCK_SERVICE_EVENTS": str(events),
                    "PATH": f"{mocks}:{environment['PATH']}",
                }
            )
            result = subprocess.run(
                ["bash", str(REPOSITORY / "install.sh"), "--skip-packages", "--skip-obsidian"],
                cwd=REPOSITORY,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
            self.assertIn("restoring the previous GoalWatch state", result.stderr)
            for target in (app, plugin, docs):
                self.assertEqual((target / "old-marker").read_text(encoding="utf-8"), "old")
            self.assertIn("old", binary.read_text(encoding="utf-8"))
            self.assertEqual(unit.read_text(encoding="utf-8"), "old unit\n")
            self.assertEqual(state.read_text(encoding="utf-8").strip(), "active")
            self.assertEqual(events.read_text(encoding="utf-8").splitlines(), ["stop", "start"])
            leftovers = list(home.rglob("*.goalwatch-previous.*"))
            leftovers += list(data.rglob("*.goalwatch-previous.*"))
            leftovers += list(config.rglob("*.goalwatch-previous.*"))
            self.assertEqual(leftovers, [])

    def test_final_service_failure_restores_shell_config_runtime_and_obsidian(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            config = root / "config"
            runtime = root / "runtime"
            mocks = root / "bin"
            state = root / "service-state"
            events = root / "events"
            failed_once = root / "failed-once"
            shell_events = root / "shell-events"
            for path in (home, data, config, runtime, mocks):
                path.mkdir(parents=True, exist_ok=True)
            state.write_text("active\n", encoding="utf-8")

            def executable(name: str, content: str) -> None:
                path = mocks / name
                path.write_text(content, encoding="utf-8")
                path.chmod(0o755)

            executable(
                "systemctl",
                """#!/usr/bin/env bash
set -eu
case "$*" in
  "--user is-active --quiet goalwatch.service") grep -qx active "$MOCK_SERVICE_STATE" ;;
  "--user stop goalwatch.service") printf 'stop\n' >>"$MOCK_EVENTS"; printf 'inactive\n' >"$MOCK_SERVICE_STATE" ;;
  "--user start goalwatch.service")
    if [[ ! -e "$MOCK_FAILED_ONCE" ]]; then
      grep -qv '^old companion$' "$MOCK_COMPANION/main.js"
      grep -q '"goal_source": "obsidian"' "$MOCK_GOALWATCH_CONFIG/config.json"
      printf 'companion-ready\nstart-failed\n' >>"$MOCK_EVENTS"
      : >"$MOCK_FAILED_ONCE"
      exit 23
    fi
    printf 'start-restored\n' >>"$MOCK_EVENTS"
    printf 'active\n' >"$MOCK_SERVICE_STATE"
    ;;
  "--user daemon-reload") exit 0 ;;
  *) exit 0 ;;
esac
""",
            )
            executable("systemd-analyze", "#!/usr/bin/env bash\nexit 0\n")
            executable(
                "omarchy",
                """#!/usr/bin/env bash
set -eu
if [[ "$*" == "plugin enable com.goalwatch --section right" ]]; then
  printf 'widget-enabled\n' >>"$MOCK_SHELL_EVENTS"
  printf '{"bar":{"layout":{"right":[{"id":"com.goalwatch"}]}}}\n' >"$MOCK_SHELL"
fi
exit 0
""",
            )
            executable("omarchy-shell", "#!/usr/bin/env bash\nexit 0\n")
            for name in ("grim", "secret-tool", "obsidian"):
                executable(name, "#!/usr/bin/env bash\nexit 0\n")

            app = data / "goalwatch" / "app"
            binary = home / ".local" / "bin" / "goalwatch"
            unit = config / "systemd" / "user" / "goalwatch.service"
            plugin = config / "omarchy" / "plugins" / "com.goalwatch"
            docs = data / "doc" / "goalwatch"
            for target in (app, plugin, docs):
                target.mkdir(parents=True)
                (target / "old-marker").write_text("old", encoding="utf-8")
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/usr/bin/env bash\nprintf 'old\\n'\n", encoding="utf-8")
            binary.chmod(0o755)
            unit.parent.mkdir(parents=True)
            unit.write_text("old unit\n", encoding="utf-8")

            shell = config / "omarchy" / "shell.json"
            shell.parent.mkdir(parents=True, exist_ok=True)
            original_shell = b'{"bar":{"layout":{"right":[]}},"keep":"exact"}\n'
            shell.write_bytes(original_shell)
            goalwatch_config = config / "goalwatch"
            goalwatch_config.mkdir()
            runtime_state = runtime / "goalwatch"
            runtime_state.mkdir()
            (runtime_state / "old-marker").write_bytes(b"old runtime\n")

            vault = home / "Vault"
            companion = vault / ".obsidian" / "plugins" / "goalwatch"
            companion.mkdir(parents=True)
            (companion / "main.js").write_bytes(b"old companion\n")
            (companion / "manifest.json").write_text(
                json.dumps({"id": "goalwatch", "version": "old"}), encoding="utf-8"
            )
            registry = vault / ".obsidian" / "community-plugins.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            original_registry = b'["other-plugin", "goalwatch"]\n'
            registry.write_bytes(original_registry)
            original_config = (
                json.dumps(
                    {
                        "version": 2,
                        "goal_source": "obsidian",
                        "obsidian_enabled": True,
                        "obsidian_vault": str(vault),
                        "manual_goal": "exact old goal",
                    },
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            (goalwatch_config / "config.json").write_bytes(original_config)
            original_manifest = (companion / "manifest.json").read_bytes()
            exact_targets = (
                app,
                binary,
                unit,
                plugin,
                docs,
                shell,
                goalwatch_config,
                runtime_state,
                companion,
                registry,
            )
            original_inodes = {
                path: (path.lstat().st_dev, path.lstat().st_ino, path.lstat().st_mode)
                for path in exact_targets
            }

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "XDG_DATA_HOME": str(data),
                    "XDG_CONFIG_HOME": str(config),
                    "XDG_STATE_HOME": str(root / "state"),
                    "XDG_RUNTIME_DIR": str(runtime),
                    "MOCK_SERVICE_STATE": str(state),
                    "MOCK_EVENTS": str(events),
                    "MOCK_FAILED_ONCE": str(failed_once),
                    "MOCK_COMPANION": str(companion),
                    "MOCK_GOALWATCH_CONFIG": str(goalwatch_config),
                    "MOCK_SHELL": str(shell),
                    "MOCK_SHELL_EVENTS": str(shell_events),
                    "PATH": f"{mocks}:{environment['PATH']}",
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(REPOSITORY / "install.sh"),
                    "--skip-packages",
                    "--vault",
                    str(vault),
                ],
                cwd=REPOSITORY,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )

            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertIn("restoring the previous GoalWatch state", result.stderr)
            self.assertEqual(shell_events.read_text(encoding="utf-8").strip(), "widget-enabled")
            self.assertEqual(shell.read_bytes(), original_shell)
            self.assertEqual((goalwatch_config / "config.json").read_bytes(), original_config)
            self.assertEqual(sorted(path.name for path in goalwatch_config.iterdir()), ["config.json"])
            self.assertEqual((runtime_state / "old-marker").read_bytes(), b"old runtime\n")
            self.assertEqual(sorted(path.name for path in runtime_state.iterdir()), ["old-marker"])
            self.assertEqual((companion / "main.js").read_bytes(), b"old companion\n")
            self.assertEqual((companion / "manifest.json").read_bytes(), original_manifest)
            self.assertEqual(registry.read_bytes(), original_registry)
            for target in (app, plugin, docs):
                self.assertEqual((target / "old-marker").read_text(encoding="utf-8"), "old")
            self.assertIn("old", binary.read_text(encoding="utf-8"))
            self.assertEqual(unit.read_text(encoding="utf-8"), "old unit\n")
            self.assertEqual(state.read_text(encoding="utf-8").strip(), "active")
            self.assertEqual(
                events.read_text(encoding="utf-8").splitlines(),
                ["stop", "companion-ready", "start-failed", "start-restored"],
            )
            self.assertEqual(
                {
                    path: (path.lstat().st_dev, path.lstat().st_ino, path.lstat().st_mode)
                    for path in exact_targets
                },
                original_inodes,
            )
            leftovers = list(home.rglob("*.goalwatch-previous.*"))
            leftovers += list(data.rglob("*.goalwatch-previous.*"))
            leftovers += list(config.rglob("*.goalwatch-previous.*"))
            leftovers += list(runtime.rglob("*.goalwatch-previous.*"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
