import subprocess
import sys
import time
import unittest

from goalwatch.process import ProcessOutputLimitError, run_bounded


class BoundedProcessTests(unittest.TestCase):
    def test_output_limit_stops_the_producer(self):
        with self.assertRaises(ProcessOutputLimitError):
            run_bounded(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 10000)"],
                timeout=2,
                stdout_limit=100,
            )

    def test_deadline_stops_the_process_group(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=0.1,
                stdout_limit=100,
            )
        self.assertLess(time.monotonic() - started, 2)

    def test_stdin_and_text_output(self):
        result = run_bounded(
            [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
            input_data="private\n",
            timeout=2,
            stdout_limit=100,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "PRIVATE")


if __name__ == "__main__":
    unittest.main()
