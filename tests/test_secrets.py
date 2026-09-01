import unittest
from unittest.mock import patch

from goalwatch import secrets


class Result:
    returncode = 0
    stdout = ""


class SecretTests(unittest.TestCase):
    @patch("goalwatch.secrets.shutil.which", return_value="/usr/bin/secret-tool")
    @patch("goalwatch.secrets.run_bounded", return_value=Result())
    def test_key_uses_stdin_not_argv(self, run, _which):
        key = "a-private-key-value-that-is-long-enough"
        secrets.set_api_key(key)
        args, kwargs = run.call_args
        self.assertNotIn(key, args[0])
        self.assertEqual(kwargs["input_data"], key + "\n")


if __name__ == "__main__":
    unittest.main()
