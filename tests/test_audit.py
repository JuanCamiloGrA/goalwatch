import base64
import json
import tempfile
import unittest
from pathlib import Path

from goalwatch.audit import AuditError, AuditStore


class AuditStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "audit.sqlite3"

    def tearDown(self):
        self.temporary.cleanup()

    def begin(self, store: AuditStore, goal: str = "Ship GoalWatch") -> int:
        return store.begin(
            model="gemini-test",
            endpoint="https://example.invalid/model",
            goal=goal,
            tools="Codex and Browser",
            request={"method": "POST", "body": {"prompt": goal}},
            image=b"\xff\xd8private-screen\xff\xd9",
        )

    def test_round_trip_keeps_exact_response_and_screenshot(self):
        raw = b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}\n'
        with AuditStore(self.database) as store:
            record_id = self.begin(store)
            store.finish(
                record_id,
                outcome="on_goal",
                raw_response=raw,
                http_status=200,
                response_headers={"content-type": "application/json"},
                latency_ms=42,
            )
            detail = store.get(record_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["raw_response"], raw.decode("utf-8"))
        self.assertEqual(detail["raw_response_encoding"], "utf-8")
        self.assertEqual(Path(detail["image_path"]).read_bytes(), b"\xff\xd8private-screen\xff\xd9")
        self.assertEqual(Path(detail["image_path"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_binary_response_is_losslessly_base64_encoded_for_the_viewer(self):
        raw = b"\xff\x00\x80"
        with AuditStore(self.database) as store:
            record_id = self.begin(store)
            store.finish(record_id, outcome="error", raw_response=raw, error_code="invalid")
            detail = store.get(record_id)
        self.assertEqual(detail["raw_response_encoding"], "base64")
        self.assertEqual(base64.b64decode(detail["raw_response"]), raw)

    def test_filters_pagination_and_clear_cover_every_record(self):
        with AuditStore(self.database) as store:
            first = self.begin(store, "Prepare report")
            store.finish(first, outcome="on_goal", raw_response=b'{"ok":true}')
            second = self.begin(store, "Watch release")
            store.finish(second, outcome="off_goal", raw_response=b'{"alert":true}')
            filtered = store.query(outcome="off_goal", query="release", limit=1)
            self.assertEqual(filtered["total"], 1)
            self.assertEqual(filtered["records"][0]["id"], second)
            self.assertEqual(store.query(limit=1, offset=1)["total"], 2)
        with AuditStore(self.database, exclusive=True) as store:
            self.assertEqual(store.clear(), 2)
            self.assertEqual(store.query()["total"], 0)
        self.assertEqual(list(self.root.glob("request-*.jpg")), [])

    def test_symlinked_database_is_refused(self):
        outside = self.root / "outside"
        outside.write_text("keep", encoding="utf-8")
        self.database.symlink_to(outside)
        with self.assertRaisesRegex(AuditError, "unsafe audit path"):
            AuditStore(self.database)
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_request_document_is_json_and_does_not_require_raw_image_duplication(self):
        with AuditStore(self.database) as store:
            record_id = self.begin(store)
            detail = store.get(record_id)
        request = json.loads(detail["request_json"])
        self.assertEqual(request["screenshot"]["bytes"], len(b"\xff\xd8private-screen\xff\xd9"))
        self.assertNotIn("private-screen", detail["request_json"])

    def test_finishing_an_unknown_record_is_refused(self):
        with AuditStore(self.database) as store:
            with self.assertRaisesRegex(AuditError, "not found"):
                store.finish(999, outcome="error", raw_response=b"")


if __name__ == "__main__":
    unittest.main()
