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


if __name__ == "__main__":
    unittest.main()
