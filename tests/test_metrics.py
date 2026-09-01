import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from goalwatch.metrics import MAX_METRICS_DB_BYTES, MAX_METRICS_WAL_BYTES, Metrics


class MetricsTests(unittest.TestCase):
    def test_symlinked_database_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_text("keep", encoding="utf-8")
            (root / "metrics.sqlite3").symlink_to(outside)
            with self.assertRaisesRegex(OSError, "unsafe metrics path"):
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
            metrics.connection.execute("UPDATE checks SET occurred_at=? WHERE id=?", (old, check))
            metrics.connection.commit()
            metrics.prune(90)
            self.assertEqual(metrics.connection.execute("SELECT count(*) FROM checks").fetchone()[0], 0)
            self.assertEqual(metrics.connection.execute("SELECT count(*) FROM alerts").fetchone()[0], 0)
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
            checks = metrics.connection.execute(
                "SELECT id FROM checks ORDER BY id"
            ).fetchall()
            alerts = metrics.connection.execute("SELECT count(*) FROM alerts").fetchone()[0]
            metrics.close()
        self.assertEqual(len(checks), 2)
        self.assertNotIn(first, [row[0] for row in checks])
        self.assertEqual(alerts, 0)

    def test_database_and_wal_have_hard_page_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics = Metrics(Path(directory) / "metrics.sqlite3")
            page_size = int(metrics.connection.execute("PRAGMA page_size").fetchone()[0])
            max_pages = int(
                metrics.connection.execute("PRAGMA max_page_count").fetchone()[0]
            )
            journal_limit = int(
                metrics.connection.execute("PRAGMA journal_size_limit").fetchone()[0]
            )
            metrics.close()
        self.assertLessEqual(page_size * max_pages, MAX_METRICS_DB_BYTES)
        self.assertEqual(journal_limit, MAX_METRICS_WAL_BYTES)


if __name__ == "__main__":
    unittest.main()
