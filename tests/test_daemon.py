import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from goalwatch.daemon import GoalWatchDaemon
from goalwatch.gemini import Decision, GeminiError
from goalwatch.goals import Goal


class DaemonDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": self.temporary.name + "/config",
                "XDG_STATE_HOME": self.temporary.name + "/state",
                "XDG_RUNTIME_DIR": self.temporary.name + "/runtime",
            },
        )
        self.environment.start()
        self.daemon = GoalWatchDaemon()

    def tearDown(self):
        self.daemon.metrics.stop_session(self.daemon.session_id)
        self.daemon.metrics.close()
        self.environment.stop()
        self.temporary.cleanup()

    def decision(self, alert, complement=""):
        return Decision(alert, complement, 45, 20, 3)

    @patch("goalwatch.daemon.capture_desktop")
    @patch("goalwatch.daemon.GeminiClient")
    def test_empty_manual_goal_stays_idle(self, client, capture):
        self.daemon._setup_state(
            {"goal_source": "manual"}, None, "configured-key", "", 300
        )
        self.assertEqual(self.daemon.state["state"], "NO GOAL")
        self.assertFalse(self.daemon.state["alert"]["active"])
        capture.assert_not_called()
        client.assert_not_called()

    @patch("goalwatch.daemon.capture_desktop", return_value=b"jpeg")
    @patch("goalwatch.daemon.GeminiClient")
    def test_on_goal_is_silent(self, client, _capture):
        client.return_value.classify.return_value = self.decision(False)
        self.daemon._perform_check(
            {"model": "gemini-test"}, Goal("Ship release", "Codex"), "private-key"
        )
        self.assertFalse(self.daemon.alert_active)
        self.assertEqual(self.daemon.state["state"], "WATCHING")
        self.assertFalse(self.daemon.state["alert"]["active"])

    @patch("goalwatch.daemon.capture_desktop", return_value=b"jpeg")
    @patch("goalwatch.daemon.GeminiClient")
    def test_off_goal_alert_persists_until_acknowledged(self, client, _capture):
        client.return_value.classify.return_value = self.decision(
            True, "This screen is unrelated to Ship release."
        )
        self.daemon._perform_check(
            {"model": "gemini-test"}, Goal("Ship release", "Codex"), "private-key"
        )
        self.assertTrue(self.daemon.alert_active)
        self.assertEqual(self.daemon.state["state"], "ALERT")
        self.assertTrue(self.daemon.state["alert"]["active"])
        self.daemon._acknowledge()
        self.assertFalse(self.daemon.alert_active)
        self.assertFalse(self.daemon.state["alert"]["active"])

    @patch("goalwatch.daemon.capture_desktop", return_value=b"jpeg")
    @patch("goalwatch.daemon.GeminiClient")
    def test_invalid_provider_metadata_cannot_terminate_or_alert(self, client, _capture):
        client.return_value.classify.side_effect = GeminiError(
            "Gemini returned invalid usage metadata.",
            "invalid_response_metadata",
        )
        self.daemon._perform_check(
            {"model": "gemini-test"}, Goal("Ship release", "Codex"), "private-key"
        )
        self.assertFalse(self.daemon.alert_active)
        self.assertEqual(self.daemon.state["state"], "WATCHING")
        self.assertEqual(self.daemon.state["last_outcome"], "error")
