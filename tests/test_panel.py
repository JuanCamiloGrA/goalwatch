from pathlib import Path
import unittest


class PanelReactivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("integrations/omarchy/com.goalwatch/Panel.qml").read_text(
            encoding="utf-8"
        )

    def test_live_durations_depend_on_panel_clock(self):
        self.assertIn("readonly property double nowMs: liveClock.date.getTime()", self.source)
        self.assertIn("function since(iso, currentTimeMs)", self.source)
        self.assertIn("function until(iso, currentTimeMs)", self.source)
        self.assertIn("root.metrics.session_started_at, root.nowMs", self.source)
        self.assertIn("root.snapshot.next_check_at, root.nowMs", self.source)
        self.assertIn('minutes + "m " + (value % 60) + "s"', self.source)

    def test_panel_clock_updates_each_second(self):
        self.assertIn("SystemClock {", self.source)
        self.assertIn("id: liveClock", self.source)
        self.assertIn("precision: SystemClock.Seconds", self.source)

    def test_private_manual_goal_uses_stdin_and_obsidian_is_one_tap(self):
        self.assertIn('command: ["goalwatch", "config", "set-manual-goal"]', self.source)
        self.assertIn("stdinEnabled: true", self.source)
        self.assertNotIn('"set-manual-goal", goal', self.source)
        self.assertIn('["goalwatch", "obsidian", enable ? "enable" : "disable"]', self.source)
        self.assertIn('text: "OBSIDIAN SYNC"', self.source)


if __name__ == "__main__":
    unittest.main()
