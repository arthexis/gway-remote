import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gway_remote.github_health import REPOSITORIES, read_snapshot


class GitHubHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "health.json"
        self.now = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)
        self.data = {
            "schema_version": 1, "status": "available",
            "completed_at": "2026-10-18T19:30:00Z",
            "repositories": [{"name": r, "pass_a_checked": True, "pass_b_checked": True}
                             for r in REPOSITORIES],
            "alerts": [],
        }

    def read(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return read_snapshot(self.path, now=self.now)

    def test_complete_snapshot(self):
        self.assertEqual(self.read()["status"], "available")

    def test_missing_snapshot(self):
        self.assertEqual(read_snapshot(self.path, now=self.now)["status"], "unavailable")

    def test_reject_extra_repo(self):
        self.data["repositories"].append({"name": "arthexis/gway", "pass_a_checked": True,
                                          "pass_b_checked": True})
        self.assertEqual(self.read()["reason"], "incomplete_scope")

    def test_reject_incomplete_pass(self):
        self.data["repositories"][0]["pass_b_checked"] = False
        self.assertEqual(self.read()["reason"], "incomplete_scope")

    def test_reject_out_of_scope_alert(self):
        self.data["alerts"] = [{"id": "bad", "repository": "arthexis/gway", "state": "ACTIVE"}]
        self.assertEqual(self.read()["reason"], "invalid_alerts")

    def test_stale(self):
        self.data["completed_at"] = "2026-10-18T16:00:00Z"
        self.assertEqual(self.read()["reason"], "stale")

    def test_corrupt(self):
        self.path.write_text("{")
        self.assertEqual(read_snapshot(self.path, now=self.now)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
