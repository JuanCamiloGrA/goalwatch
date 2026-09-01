import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from goalwatch.metrics import Metrics


class MetricsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
