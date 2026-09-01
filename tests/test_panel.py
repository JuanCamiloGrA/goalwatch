from pathlib import Path
import unittest


class PanelReactivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("integrations/omarchy/com.goalwatch/Panel.qml").read_text(
            encoding="utf-8"
        )
        cls.service = Path("integrations/omarchy/com.goalwatch/Service.qml").read_text(
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

    def test_untrusted_runtime_text_is_plain_and_bounded(self):
        self.assertIn("String(parsed.goal).slice(0, 2000)", self.service)
        self.assertIn("String(alert.complement).slice(0, 700)", self.service)
        self.assertGreaterEqual(self.service.count("textFormat: Text.PlainText"), 2)
        self.assertIn("root.bounded(root.snapshot.goal", self.source)
        self.assertIn("root.snapshot.error ||", self.source)
        self.assertGreaterEqual(self.source.count("textFormat: Text.PlainText"), 8)

    def test_audit_browser_uses_stdin_filters_and_shows_capture_and_raw_response(self):
        self.assertIn('command: ["goalwatch", "audit", "query"]', self.source)
        self.assertIn('"query": String(auditSearchField.text || "").slice(0, 200)', self.source)
        self.assertIn("auditQueryProc.payload", self.source)
        self.assertIn("stdinEnabled: true", self.source)
        self.assertNotIn('"audit", "query", auditSearchField', self.source)
        self.assertIn("source: root.auditImageUrl(root.selectedAudit.image_path)", self.source)
        self.assertIn("root.selectedAudit.raw_response", self.source)
        self.assertIn('target: "com.goalwatch.audit"', self.source)
        self.assertIn('{"label": "PENDING", "value": "pending"}', self.source)
        self.assertIn('text: "REQUEST AUDIT"', self.source)


if __name__ == "__main__":
    unittest.main()
