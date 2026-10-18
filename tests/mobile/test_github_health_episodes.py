import sqlite3
import unittest

from gway_remote.github_health_episodes import reconcile


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

    def rows(self, conclusions):
        return [{
            "name": "arthexis/gway-remote",
            "ci_lanes": [{
                "workflow": "Python checks", "trigger": "push", "branch": "main",
                "completed_runs": [
                    {"id": i + 1, "conclusion": conclusion,
                     "url": "https://github.com/arthexis/gway-remote/actions/runs/" + str(i + 1)}
                    for i, conclusion in enumerate(conclusions)]
            }]
        }]

    def test_two_failures_open_and_success_resolves_once(self):
        self.assertEqual(reconcile(self.db, self.rows(["failure"]), "t1"), [])
        active = reconcile(self.db, self.rows(["failure", "failure"]), "t2")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["state"], "ACTIVE")
        self.assertEqual(reconcile(self.db, self.rows(["failure", "failure"]), "t3")[0]["state"], "ACTIVE")
        resolved = reconcile(self.db, self.rows(["success", "failure"]), "t4")
        self.assertEqual(resolved[0]["resolution_kind"], "fixed")
        self.assertEqual(reconcile(self.db, self.rows(["success", "failure"]), "t5"), [])

    def test_old_failure_cannot_reopen_resolved_episode(self):
        reconcile(self.db, self.rows(["failure", "failure"]), "t1")
        reconcile(self.db, self.rows(["success", "failure"]), "t2")
        self.assertEqual(reconcile(self.db, self.rows(["failure", "failure"]), "t3"), [])

    def test_single_failure_is_not_an_alert(self):
        self.assertEqual(reconcile(self.db, self.rows(["failure", "success"]), "t1"), [])

    def test_different_lanes_do_not_resolve(self):
        reconcile(self.db, self.rows(["failure", "failure"]), "t1")
        rows = self.rows(["success", "success"])
        rows[0]["ci_lanes"][0]["trigger"] = "pull_request"
        self.assertEqual(reconcile(self.db, rows, "t2"), [])


if __name__ == "__main__":
    unittest.main()
