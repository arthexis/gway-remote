import sqlite3
import unittest

from gway_remote.github_health_episodes import reconcile


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

    def rows(self, conclusions, newest_id=10):
        return [{
            "name": "arthexis/gway-remote",
            "ci_lanes": [{
                "workflow": "Python checks", "trigger": "push", "branch": "main",
                "completed_runs": [
                    {"id": newest_id - i, "conclusion": conclusion,
                     "url": "https://github.com/arthexis/gway-remote/actions/runs/" + str(newest_id - i)}
                    for i, conclusion in enumerate(conclusions)]
            }]
        }]

    def test_two_failures_open_and_success_resolves_once(self):
        self.assertEqual(reconcile(self.db, self.rows(["failure"]), "t1"), [])
        active = reconcile(self.db, self.rows(["failure", "failure"], newest_id=11), "t2")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["state"], "ACTIVE")
        self.assertEqual(reconcile(self.db, self.rows(["failure", "failure"], newest_id=11), "t3")[0]["state"], "ACTIVE")
        resolved = reconcile(self.db, self.rows(["success", "failure"], newest_id=12), "t4")
        self.assertEqual(resolved[0]["resolution_kind"], "fixed")
        self.assertEqual(reconcile(self.db, self.rows(["success", "failure"], newest_id=12), "t5"), [])

    def test_old_failure_cannot_reopen_resolved_episode(self):
        reconcile(self.db, self.rows(["failure", "failure"], newest_id=11), "t1")
        reconcile(self.db, self.rows(["success", "failure"], newest_id=12), "t2")
        self.assertEqual(reconcile(self.db, self.rows(["failure", "failure"], newest_id=11), "t3"), [])

    def test_closed_pr_resolves_active_failure_without_claiming_ci_fixed(self):
        rows = self.rows(["failure", "failure"])
        lane = rows[0]["ci_lanes"][0]
        lane.update(trigger="pull_request", branch="feature/old-pr", pr_lifecycle="open")
        self.assertEqual(reconcile(self.db, rows, "t1")[0]["state"], "ACTIVE")
        lane["pr_lifecycle"] = "closed"
        resolved = reconcile(self.db, rows, "t2")
        self.assertEqual(resolved[0]["state"], "RESOLVED")
        self.assertEqual(resolved[0]["resolution_kind"], "pr_closed")
        self.assertEqual(reconcile(self.db, rows, "t3"), [])

    def test_open_or_unverified_pr_remains_active(self):
        rows = self.rows(["failure", "failure"])
        lane = rows[0]["ci_lanes"][0]
        lane.update(trigger="pull_request", branch="feature/ongoing")
        reconcile(self.db, rows, "t1")
        self.assertEqual(reconcile(self.db, rows, "t2")[0]["state"], "ACTIVE")
        lane["pr_lifecycle"] = "open"
        self.assertEqual(reconcile(self.db, rows, "t3")[0]["state"], "ACTIVE")

    def test_main_lane_is_not_retired(self):
        rows = self.rows(["failure", "failure"])
        rows[0]["ci_lanes"][0]["pr_lifecycle"] = "closed"
        reconcile(self.db, rows, "t1")
        self.assertEqual(reconcile(self.db, rows, "t2")[0]["state"], "ACTIVE")

    def test_single_failure_is_not_an_alert(self):
        self.assertEqual(reconcile(self.db, self.rows(["failure", "success"]), "t1"), [])

    def test_different_lanes_do_not_resolve(self):
        reconcile(self.db, self.rows(["failure", "failure"]), "t1")
        rows = self.rows(["success", "success"])
        rows[0]["ci_lanes"][0]["trigger"] = "pull_request"
        self.assertEqual(reconcile(self.db, rows, "t2"), [])


if __name__ == "__main__":
    unittest.main()
