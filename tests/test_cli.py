import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stderr
from unittest.mock import patch

from goalwatch.cli import build_parser, command_audit, command_config


class CliPrivacyTests(unittest.TestCase):
    def test_manual_goal_command_accepts_no_private_argv_value(self):
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["config", "set-manual-goal", "private goal"])

    @patch("goalwatch.cli.notify_reload")
    @patch("goalwatch.cli.set_manual_goal")
    def test_manual_goal_payload_is_read_from_stdin_and_not_echoed(self, setter, _reload):
        payload = {"goal": "Private goal", "tools": "Private tools"}
        arguments = Namespace(config_action="set-manual-goal")
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(payload) + "\n")), patch("sys.stdout", output):
            self.assertEqual(command_config(arguments), 0)
        setter.assert_called_once_with("Private goal", "Private tools")
        self.assertEqual(json.loads(output.getvalue()), {"saved": True})
        self.assertNotIn("Private goal", output.getvalue())
        self.assertNotIn("Private tools", output.getvalue())

    def test_audit_filter_accepts_no_private_argv_query(self):
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["audit", "query", "private search"])

    @patch("goalwatch.cli.AuditStore")
    def test_audit_filter_is_read_from_stdin(self, store_type):
        store = store_type.return_value.__enter__.return_value
        store.query.return_value = {"total": 0, "limit": 50, "offset": 0, "records": []}
        arguments = Namespace(audit_action="query")
        output = io.StringIO()
        payload = {"outcome": "error", "query": "private search", "limit": 50, "offset": 0}
        with patch("sys.stdin", io.StringIO(json.dumps(payload) + "\n")), patch(
            "sys.stdout", output
        ):
            self.assertEqual(command_audit(arguments), 0)
        store.query.assert_called_once_with(
            outcome="error", query="private search", limit=50, offset=0
        )
        self.assertNotIn("private search", output.getvalue())


if __name__ == "__main__":
    unittest.main()
