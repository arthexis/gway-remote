import sqlite3
import unittest

from gway_remote.github_health_prs import reconcile_prs


class PRBlockerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

    def rows(self, *, verified=True, draft=False, sha="abc"):
        return [{"name": "arthexis/gway-remote", "pr_evidence": [{
            "number": 42, "head_sha": sha, "url": "https://github.com/arthexis/gway-remote/pull/42",
            "draft": draft, "on_hold": False, "head_check": "failure",
            "required_check_verified": verified}]}]

    def test_requires_one_hour_of_same_head_and_verified_requirement(self):
        self.assertEqual(reconcile_prs(self.db, self.rows(), "2026-10-18T12:00:00Z"), [])
        self.assertEqual(reconcile_prs(self.db, self.rows(), "2026-10-18T12:59:00Z"), [])
        alerts = reconcile_prs(self.db, self.rows(), "2026-10-18T13:00:00Z")
        self.assertEqual(alerts[0]["category"], "CI_FAILURE_STUCK")
        self.assertEqual(reconcile_prs(self.db, self.rows(sha="new"), "2026-10-18T13:01:00Z"), [])

    def test_unverified_check_never_alerts(self):
        self.assertEqual(reconcile_prs(self.db, self.rows(verified=False), "2026-10-18T12:00:00Z"), [])
        self.assertEqual(reconcile_prs(self.db, self.rows(verified=False), "2026-10-18T15:00:00Z"), [])

    def test_draft_does_not_alert(self):
        self.assertEqual(reconcile_prs(self.db, self.rows(draft=True), "2026-10-18T12:00:00Z"), [])
        self.assertEqual(reconcile_prs(self.db, self.rows(draft=True), "2026-10-18T15:00:00Z"), [])


if __name__ == "__main__":
    unittest.main()
