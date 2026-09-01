import json
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from goalwatch.gemini import MAX_RESPONSE_BYTES, GeminiClient, GeminiError
from goalwatch.goals import Goal


class Handler(BaseHTTPRequestHandler):
    response_text = '{"alert":false,"complement":""}'
    response_status = 200
    last_headers = None
    last_payload = None
    paths = []
    redirect_location = ""
    declared_length = None

    def do_POST(self):
        Handler.paths.append(self.path)
        if Handler.redirect_location:
            self.send_response(307)
            self.send_header("location", Handler.redirect_location)
            self.end_headers()
            return
        length = int(self.headers.get("content-length", "0"))
        Handler.last_payload = json.loads(self.rfile.read(length))
        Handler.last_headers = self.headers
        body = json.dumps(
            {
                "candidates": [{"content": {"parts": [{"text": Handler.response_text}]}}],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 4},
            }
        ).encode()
        self.send_response(Handler.response_status)
        self.send_header("content-type", "application/json")
        self.send_header(
            "content-length",
            str(Handler.declared_length if Handler.declared_length is not None else len(body)),
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class GeminiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/models/{{model}}:generateContent"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def client(self):
        return GeminiClient("private-key-value", "gemini-test", endpoint=self.endpoint)

    def setUp(self):
        Handler.response_status = 200
        Handler.redirect_location = ""
        Handler.declared_length = None
        Handler.paths = []

    def test_false_decision_and_usage(self):
        Handler.response_text = '{"alert":false,"complement":""}'
        result = self.client().classify(Goal("Ship", "Codex"), b"jpeg")
        self.assertFalse(result.alert)
        self.assertEqual(result.prompt_tokens, 12)
        self.assertEqual(Handler.last_headers["x-goog-api-key"], "private-key-value")
        generation = Handler.last_payload["generationConfig"]
        self.assertEqual(generation["responseMimeType"], "application/json")
        self.assertEqual(set(generation["responseJsonSchema"]["properties"]), {"alert", "complement"})

    def test_true_decision(self):
        Handler.response_text = '{"alert":true,"complement":"This is unrelated to Ship."}'
        result = self.client().classify(Goal("Ship", "Codex"), b"jpeg")
        self.assertTrue(result.alert)

    def test_extra_field_is_rejected(self):
        Handler.response_text = '{"alert":false,"complement":"","extra":1}'
        with self.assertRaises(GeminiError):
            self.client().classify(Goal("Ship", "Codex"), b"jpeg")

    def test_non_alert_explanation_is_rejected(self):
        Handler.response_text = '{"alert":false,"complement":"No."}'
        with self.assertRaises(GeminiError):
            self.client().classify(Goal("Ship", "Codex"), b"jpeg")

    def test_rate_limit_is_classified(self):
        Handler.response_status = 429
        with self.assertRaises(GeminiError) as raised:
            self.client().classify(Goal("Ship", "Codex"), b"jpeg")
        self.assertEqual(raised.exception.code, "rate_limited")

    def test_redirect_is_rejected_without_replaying_the_api_key(self):
        Handler.redirect_location = f"http://127.0.0.1:{self.server.server_port}/redirected"
        with self.assertRaises(GeminiError) as raised:
            self.client().classify(Goal("Ship", "Codex"), b"jpeg")
        self.assertEqual(raised.exception.code, "redirect_rejected")
        self.assertEqual(len(Handler.paths), 1)

    def test_declared_oversized_response_is_rejected_before_reading(self):
        Handler.declared_length = MAX_RESPONSE_BYTES + 1
        with self.assertRaises(GeminiError) as raised:
            self.client().classify(Goal("Ship", "Codex"), b"jpeg")
        self.assertEqual(raised.exception.code, "response_size")

    def test_oversized_image_is_rejected_before_network(self):
        with self.assertRaises(GeminiError) as raised:
            self.client().classify(Goal("Ship", "Codex"), b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(raised.exception.code, "image_size")

    @patch("goalwatch.gemini.urllib.request.build_opener")
    def test_network_failure_is_classified(self, opener):
        opener.return_value.open.side_effect = urllib.error.URLError("offline")
        with self.assertRaises(GeminiError) as raised:
            self.client().classify(Goal("Ship", "Codex"), b"jpeg")
        self.assertEqual(raised.exception.code, "network")


if __name__ == "__main__":
    unittest.main()
