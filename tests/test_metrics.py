import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from goalwatch.database import LEGACY_AUXILIARY_SUFFIXES
from goalwatch.metrics import MAX_METRICS_DB_BYTES, Metrics


class MetricsTests(unittest.TestCase):
    def test_symlinked_database_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_text("keep", encoding="utf-8")
            (root / "metrics.sqlite3").symlink_to(outside)
            with self.assertRaises(OSError):
                Metrics(root / "metrics.sqlite3")
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_summary_and_alert_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics = Metrics(Path(directory) / "metrics.sqlite3")
            session = metrics.start_session()
            metrics.record_check(session, "on_goal", "test", latency_ms=100, image_bytes=10)
            check = metrics.record_check(session, "off_goal", "test", latency_ms=300, image_bytes=20)
            alert = metrics.create_alert(check)
            metrics.acknowledge_alert(alert)
            metrics.record_check(session, "on_goal", "test", latency_ms=200, image_bytes=30)
            summary = metrics.summary(session)
            self.assertEqual(summary["focus_score"], 67)
            self.assertEqual(summary["alerts_today"], 1)
            self.assertEqual(summary["median_latency_ms"], 200)
            self.assertEqual(summary["image_bytes_today"], 60)
            self.assertTrue(summary["streak_started_at"])
            metrics.stop_session(session)
            metrics.close()

    def test_prune_removes_old_checks_and_their_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics = Metrics(Path(directory) / "metrics.sqlite3")
            session = metrics.start_session()
            check = metrics.record_check(session, "off_goal", "test")
            metrics.create_alert(check)
            old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat(timespec="seconds")
            with metrics._operation(write=True):
                metrics.connection.execute(
                    "UPDATE checks SET occurred_at=? WHERE id=?", (old, check)
                )
            metrics.prune(90)
            with metrics._operation(write=False):
                self.assertEqual(
                    metrics.connection.execute("SELECT count(*) FROM checks").fetchone()[0], 0
                )
                self.assertEqual(
                    metrics.connection.execute("SELECT count(*) FROM alerts").fetchone()[0], 0
                )
            metrics.close()

    def test_check_row_quota_keeps_only_the_newest_rows(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "goalwatch.metrics.MAX_CHECK_ROWS", 2
        ):
            metrics = Metrics(Path(directory) / "metrics.sqlite3")
            session = metrics.start_session()
            first = metrics.record_check(session, "off_goal", "test")
            metrics.create_alert(first)
            metrics.record_check(session, "on_goal", "test")
            metrics.record_check(session, "on_goal", "test")
            with metrics._operation(write=False):
                checks = metrics.connection.execute(
                    "SELECT id FROM checks ORDER BY id"
                ).fetchall()
                alerts = metrics.connection.execute("SELECT count(*) FROM alerts").fetchone()[0]
            metrics.close()
        self.assertEqual(len(checks), 2)
        self.assertNotIn(first, [row[0] for row in checks])
        self.assertEqual(alerts, 0)

    def test_database_snapshot_has_a_hard_page_limit_and_no_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = Metrics(root / "metrics.sqlite3")
            with metrics._operation(write=False):
                page_size = int(metrics.connection.execute("PRAGMA page_size").fetchone()[0])
                max_pages = int(
                    metrics.connection.execute("PRAGMA max_page_count").fetchone()[0]
                )
            metrics.close()
            for suffix in LEGACY_AUXILIARY_SUFFIXES:
                self.assertFalse((root / f"metrics.sqlite3{suffix}").exists())
        self.assertLessEqual(page_size * max_pages, MAX_METRICS_DB_BYTES)

    def test_two_open_metrics_stores_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.sqlite3"
            first = Metrics(path)
            second = Metrics(path)
            try:
                first_session = first.start_session()
                second_session = second.start_session()
                first.record_check(first_session, "on_goal", "one")
                second.record_check(second_session, "off_goal", "two")
                with first._operation(write=False):
                    count = first.connection.execute("SELECT count(*) FROM checks").fetchone()[0]
                self.assertEqual(count, 2)
            finally:
                second.close()
                first.close()

    def test_legacy_sidecar_hardlink_is_refused_without_touching_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "metrics.sqlite3"
            Metrics(path).close()
            outside = root / "outside"
            outside.write_bytes(b"do not touch")
            os.link(outside, root / "metrics.sqlite3-shm")
            with self.assertRaisesRegex(OSError, "auxiliary path"):
                Metrics(path)
            self.assertEqual(outside.read_bytes(), b"do not touch")


if __name__ == "__main__":
    unittest.main()
