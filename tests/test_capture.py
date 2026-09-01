import unittest
from unittest.mock import patch

from goalwatch.capture import CaptureError, _capture_scale, _jpeg_size, capture_desktop


JPEG_320_X_200 = (
    b"\xff\xd8"
    b"\xff\xc0\x00\x11\x08\x00\xc8\x01\x40\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    b"\xff\xd9"
)


class CaptureTests(unittest.TestCase):
    def test_virtual_desktop_is_scaled_to_1920(self):
        monitors = [
            {"x": 0, "y": 0, "width": 1920, "height": 1080},
            {"x": 1920, "y": 0, "width": 1920, "height": 1080},
        ]
        self.assertEqual(_capture_scale(monitors), 0.5)

    def test_jpeg_dimensions(self):
        self.assertEqual(_jpeg_size(JPEG_320_X_200), (320, 200))

    @patch("goalwatch.capture._session_locked", return_value=True)
    @patch("goalwatch.capture.shutil.which", return_value="/usr/bin/grim")
    def test_locked_session_skips_capture(self, _which, _locked):
        with self.assertRaisesRegex(CaptureError, "locked"):
            capture_desktop()
