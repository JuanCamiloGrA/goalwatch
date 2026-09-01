import json
import tempfile
import unittest
from pathlib import Path

from goalwatch.state import read_state, write_state


class StateIoTests(unittest.TestCase):
    def test_state_symlink_is_replaced_without_touching_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.json"
            outside.write_text('{"keep":true}\n', encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()
            state = runtime / "state.json"
            state.symlink_to(outside)
            write_state({"state": "OFF"}, state)
            self.assertFalse(state.is_symlink())
            self.assertEqual(outside.read_text(encoding="utf-8"), '{"keep":true}\n')
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["state"], "OFF")

    def test_symlinked_runtime_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            runtime = root / "runtime"
            runtime.symlink_to(outside, target_is_directory=True)
            target = runtime / "state.json"
            self.assertEqual(read_state(target)["state"], "OFF")
            with self.assertRaises(OSError):
                write_state({"state": "WATCHING"}, target)
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
