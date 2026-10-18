import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gway_remote.github_health import REPOSITORIES, read_snapshot
from gway_remote.github_health_publish import publish


class SnapshotPublishTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "input.json"
        self.destination = Path(self.directory.name) / "state" / "watch.json"
        self.document = {
            "schema_version": 1,
            "status": "available",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "repositories": [
                {"name": name, "pass_a_checked": True, "pass_b_checked": True}
                for name in REPOSITORIES
            ],
            "alerts": [],
        }

    def write(self):
        self.source.write_text(json.dumps(self.document), encoding="utf-8")

    def test_atomic_publish_and_read(self):
        self.write()
        publish(self.source, self.destination)
        self.assertEqual(read_snapshot(self.destination)["status"], "available")
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)

    def test_invalid_update_preserves_previous_snapshot(self):
        self.write()
        publish(self.source, self.destination)
        previous = self.destination.read_bytes()
        self.document["repositories"].pop()
        self.write()
        with self.assertRaises(ValueError):
            publish(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), previous)

    def test_reject_unapproved_alert_repo(self):
        self.document["alerts"].append(
            {"id": "bad", "state": "ACTIVE", "repository": "arthexis/gway"})
        self.write()
        with self.assertRaises(ValueError):
            publish(self.source, self.destination)

    def test_reject_stale(self):
        self.document["completed_at"] = "2020-01-01T00:00:00Z"
        self.write()
        with self.assertRaises(ValueError):
            publish(self.source, self.destination)


if __name__ == "__main__":
    unittest.main()
