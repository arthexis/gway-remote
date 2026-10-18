import sqlite3
import unittest
from gway_remote.github_health_categories import signals, reconcile_extra
from gway_remote.github_health_pending import reconcile_pending

REPO = "arthexis/gway-remote"


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.t1 = "2026-10-18T12:00:00Z"
        self.t2 = "2026-10-18T13:01:00Z"

    def row(self, **overrides):
        pr = {"number": 7, "head_sha": "a" * 40,
              "url": "https://github.com/arthexis/gway-remote/pull/7",
              "draft": False, "on_hold": False, "review_blocked": True,
              "mergeable_state": "unknown", "missing_required_checks": [],
              "auto_merge_enabled": False, "checks_pending": False,
              "checks_failing": False, "required_check_count": 0,
              "age_seconds": 10000}
        pr.update(overrides)
        return [{"name": REPO, "pr_evidence": [pr]}]

    def test_evidence_gates_all_pr_categories(self):
        self.assertIn("REVIEW_BLOCKED", signals(self.row()[0]["pr_evidence"][0]))
        self.assertIn("BRANCH_FRESHNESS_BLOCKED", signals(
            self.row(mergeable_state="dirty")[0]["pr_evidence"][0]))
        self.assertIn("CI_MISSING", signals(
            self.row(missing_required_checks=["ci"])[0]["pr_evidence"][0]))
        self.assertIn("READY_BUT_NOT_MERGING", signals(
            self.row(review_blocked=False, auto_merge_enabled=True,
                     mergeable_state="clean")[0]["pr_evidence"][0]))
        self.assertEqual(signals(self.row(draft=True)[0]["pr_evidence"][0]), {})

    def test_persistent_alert_and_once_only_resolution(self):
        self.assertEqual(reconcile_extra(self.db, self.row(), self.t1), [])
        active = reconcile_extra(self.db, self.row(), self.t2)
        self.assertEqual(active[0]["state"], "ACTIVE")
        changed = self.row(review_blocked=False)
        resolved = reconcile_extra(self.db, changed, "2026-10-18T13:02:00Z")
        self.assertEqual(resolved[0]["state"], "RESOLVED")
        self.assertEqual(reconcile_extra(self.db, changed, "2026-10-18T13:03:00Z"), [])

    def test_no_false_fix_for_absent_pr(self):
        reconcile_extra(self.db, self.row(), self.t1)
        reconcile_extra(self.db, self.row(), self.t2)
        results = reconcile_extra(self.db, [{"name": REPO, "pr_evidence": []}],
                                  "2026-10-18T13:02:00Z")
        self.assertEqual(results[0]["resolution_kind"], "closed_without_verified_fix")

    def test_long_running_ci_notified_once_on_clearance(self):
        pending = [{"name": REPO, "pending_runs": [
            {"id": 123, "name": "Python checks", "status": "in_progress",
             "created_at": "2026-10-18T10:00:00Z",
             "url": "https://github.com/arthexis/gway-remote/actions/runs/123"}]}]
        active = reconcile_pending(self.db, pending, self.t2)
        self.assertEqual(active[0]["category"], "STALE_IN_PROGRESS")
        done = [{"name": REPO, "pending_runs": []}]
        resolved = reconcile_pending(self.db, done, "2026-10-18T13:02:00Z")
        self.assertEqual(resolved[0]["resolution_kind"], "no_longer_observed")
        self.assertEqual(reconcile_pending(self.db, done, "2026-10-18T13:03:00Z"), [])


if __name__ == "__main__":
    unittest.main()
