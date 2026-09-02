import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from goalwatch.audit import (
    MAX_AUDIT_DB_BYTES,
    AuditError,
    AuditStore,
)
from goalwatch.database import LEGACY_AUXILIARY_SUFFIXES


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
        response = self.root / f"response-{record_id:08d}.bin"
        self.assertEqual(response.read_bytes(), raw)
        self.assertEqual(response.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)
        for suffix in LEGACY_AUXILIARY_SUFFIXES:
            self.assertFalse((self.root / f"audit.sqlite3{suffix}").exists())

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
        self.assertEqual(list(self.root.glob("response-*.bin")), [])

    def test_symlinked_database_is_refused(self):
        outside = self.root / "outside"
        outside.write_text("keep", encoding="utf-8")
        self.database.symlink_to(outside)
        with self.assertRaises(AuditError):
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

    def test_row_quota_evicts_the_oldest_request_and_its_capture(self):
        with patch("goalwatch.audit.MAX_AUDIT_ROWS", 2), AuditStore(self.database) as store:
            first = self.begin(store, "First")
            store.finish(first, outcome="on_goal", raw_response=b"one")
            first_image = Path(store.get(first)["image_path"])
            first_response = self.root / f"response-{first:08d}.bin"
            second = self.begin(store, "Second")
            store.finish(second, outcome="on_goal", raw_response=b"two")
            third = self.begin(store, "Third")
            store.finish(third, outcome="on_goal", raw_response=b"three")
            page = store.query()
        self.assertEqual([row["id"] for row in page["records"]], [third, second])
        self.assertFalse(first_image.exists())
        self.assertFalse(first_response.exists())

    def test_quota_never_evicts_an_in_flight_request(self):
        with patch("goalwatch.audit.MAX_AUDIT_ROWS", 1), AuditStore(self.database) as store:
            first = self.begin(store, "In flight")
            with self.assertRaisesRegex(AuditError, "quota"):
                self.begin(store, "Cannot displace it")
            detail = store.get(first)
        self.assertEqual(detail["outcome"], "pending")

    def test_retention_prunes_expired_request_and_capture(self):
        with AuditStore(self.database) as store:
            record_id = self.begin(store)
            store.finish(record_id, outcome="on_goal", raw_response=b"ok")
            image = Path(store.get(record_id)["image_path"])
            expired = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(
                timespec="seconds"
            )
            with store._data_lock():
                store._reload_locked()
                store.connection.execute(
                    "UPDATE requests SET requested_at=? WHERE id=?",
                    (expired, record_id),
                )
                store._save_locked()
            self.assertEqual(store.prune(), 1)
            self.assertEqual(store.query()["total"], 0)
        self.assertFalse(image.exists())

    def test_content_quota_is_enforced_before_the_next_request(self):
        image_size = len(b"\xff\xd8private-screen\xff\xd9")
        with patch("goalwatch.audit.MAX_AUDIT_CONTENT_BYTES", image_size * 2):
            with AuditStore(self.database) as store:
                first = self.begin(store, "First")
                store.finish(first, outcome="on_goal", raw_response=b"")
                second = self.begin(store, "Second")
                store.finish(second, outcome="on_goal", raw_response=b"")
                third = self.begin(store, "Third")
                page = store.query()
        self.assertEqual([row["id"] for row in page["records"]], [third, second])
        self.assertNotIn(first, [row["id"] for row in page["records"]])

    def test_response_quota_removes_the_oldest_completed_response(self):
        with patch("goalwatch.audit.MAX_AUDIT_RESPONSE_BYTES", 5):
            with AuditStore(self.database) as store:
                first = self.begin(store, "First")
                store.finish(first, outcome="on_goal", raw_response=b"1234")
                second = self.begin(store, "Second")
                store.finish(second, outcome="on_goal", raw_response=b"5678")
                page = store.query()
        self.assertEqual([row["id"] for row in page["records"]], [second])
        self.assertFalse((self.root / f"response-{first:08d}.bin").exists())

    def test_query_exposes_the_retention_policy(self):
        with AuditStore(self.database) as store:
            page = store.query()
        self.assertEqual(page["retention_days"], 7)
        self.assertEqual(page["max_records"], 2_000)
        self.assertEqual(page["max_content_bytes"], 512 * 1024 * 1024)

    def test_directory_entry_quota_fails_closed_before_any_request(self):
        for index in range(3):
            (self.root / f"unrelated-{index}").write_text("x", encoding="utf-8")
        with patch("goalwatch.audit.MAX_AUDIT_DIRECTORY_ENTRIES", 2):
            with self.assertRaisesRegex(AuditError, "entry quota"):
                AuditStore(self.database)

    def test_database_snapshot_has_a_hard_page_limit(self):
        with AuditStore(self.database) as store:
            with store._data_lock():
                store._reload_locked()
                page_size = int(store.connection.execute("PRAGMA page_size").fetchone()[0])
                max_pages = int(
                    store.connection.execute("PRAGMA max_page_count").fetchone()[0]
                )
        self.assertLessEqual(page_size * max_pages, MAX_AUDIT_DB_BYTES)

    def test_two_open_stores_cannot_overwrite_each_others_records(self):
        first_store = AuditStore(self.database)
        second_store = AuditStore(self.database)
        try:
            first = self.begin(first_store, "First")
            second = self.begin(second_store, "Second")
            first_store.finish(first, outcome="on_goal", raw_response=b"one")
            second_store.finish(second, outcome="off_goal", raw_response=b"two")
            self.assertEqual(first_store.query()["total"], 2)
            self.assertEqual(second_store.query()["total"], 2)
        finally:
            second_store.close()
            first_store.close()

    def test_legacy_sidecar_hardlinks_are_refused_without_touching_their_target(self):
        with AuditStore(self.database):
            pass
        outside = self.root / "outside"
        outside.write_bytes(b"do not touch")
        os.link(outside, self.root / "audit.sqlite3-wal")
        with self.assertRaises(AuditError):
            AuditStore(self.database)
        self.assertEqual(outside.read_bytes(), b"do not touch")

    def test_unsafe_response_replacement_is_not_read(self):
        raw = b"provider response"
        with AuditStore(self.database) as store:
            record_id = self.begin(store)
            store.finish(record_id, outcome="on_goal", raw_response=raw)
            response = self.root / f"response-{record_id:08d}.bin"
            response.unlink()
            outside = self.root / "outside-response"
            outside.write_bytes(raw)
            response.symlink_to(outside)
            with self.assertRaisesRegex(AuditError, "unavailable or unsafe"):
                store.get(record_id)
        self.assertEqual(outside.read_bytes(), raw)

    def test_legacy_inline_response_remains_readable_without_destructive_migration(self):
        raw = b"legacy searchable provider response"
        with AuditStore(self.database) as store:
            record_id = self.begin(store)
            store.finish(record_id, outcome="on_goal", raw_response=raw)
            response = self.root / f"response-{record_id:08d}.bin"
            with store._data_lock():
                store._reload_locked()
                store.connection.execute(
                    """
                    UPDATE requests SET response_body=?, response_file='', response_search=''
                    WHERE id=?
                    """,
                    (raw, record_id),
                )
                store._save_locked()
            response.unlink()
        with AuditStore(self.database) as store:
            detail = store.get(record_id)
            page = store.query(query="searchable provider")
        self.assertEqual(detail["raw_response"].encode("utf-8"), raw)
        self.assertEqual(page["total"], 1)
        self.assertFalse(response.exists())


if __name__ == "__main__":
    unittest.main()
