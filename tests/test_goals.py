import tempfile
import unittest
from pathlib import Path

from goalwatch.config import DEFAULT_TOOLS
from goalwatch.goals import GoalReadError, parse_latest_goal, read_latest_goal


class GoalParserTests(unittest.TestCase):
    def test_latest_valid_goal_wins(self):
        result = parse_latest_goal(
            "> Current Goal: First\n>\n> Available Tools: One\n\n"
            "> Current Goal: Second\n>\n> Available Tools: Two\n"
        )
        self.assertEqual(result.description, "Second")
        self.assertEqual(result.tools, "Two")

    def test_malformed_tail_does_not_erase_previous_goal(self):
        result = parse_latest_goal("> Current Goal: Valid\n> Available Tools: Tools\n> Current Goal:   \n")
        self.assertEqual(result.description, "Valid")

    def test_missing_tools_uses_default(self):
        result = parse_latest_goal("> Current Goal: Ship it\r\n")
        self.assertEqual(result.tools, DEFAULT_TOOLS)

    def test_unrelated_quote_is_ignored(self):
        self.assertIsNone(parse_latest_goal("> Current objective: nope\n> Available Tools: A"))

    def test_oversized_goal_block_is_ignored(self):
        markdown = f"> Current Goal: {'x' * 2001}\n>\n> Available Tools: Codex"
        self.assertIsNone(parse_latest_goal(markdown))

    def test_unicode(self):
        result = parse_latest_goal("> Current Goal: Terminar revisión ✅\n>\n> Available Tools: Codex y Obsidian")
        self.assertEqual(result.description, "Terminar revisión ✅")

    def test_read_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            note = base / "note.md"
            note.write_text("> Current Goal: A", encoding="utf-8")
            link = base / "link.md"
            link.symlink_to(note)
            self.assertIsNone(read_latest_goal(str(link)))

    def test_read_rejects_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / "note.md"
            note.write_bytes(b"\xff")
            with self.assertRaises(GoalReadError):
                read_latest_goal(str(note))


if __name__ == "__main__":
    unittest.main()
