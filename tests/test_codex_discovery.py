import tempfile
import unittest
from pathlib import Path
from gway_remote.codex_queue import TaskQueue
from gway_remote.codex_discovery import discover
from gway_remote.codex_policy import TRUSTED_CREATOR_ID


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = TaskQueue(Path(self.tmp.name) / "queue.db")

    def tearDown(self):
        self.queue.close()
        self.tmp.cleanup()

    def test_only_creator_and_issue_imported(self):
        issues = [
            {"number": 37, "user": {"id": TRUSTED_CREATOR_ID, "login": "arthexis"}},
            {"number": 38, "user": {"id": 123, "login": "stranger"}},
            {"number": 39, "user": {"id": TRUSTED_CREATOR_ID, "login": "arthexis"}, "pull_request": {}},
        ]
        fetch = lambda repo, token: iter(issues)
        result = discover(self.queue, "token", repositories=["arthexis/gway-remote"], fetcher=fetch)
        self.assertEqual(result, {"imported": 1, "existing": 0, "ignored": 2})
        self.assertEqual(self.queue.list()[0]["state"], "requested")
        self.assertEqual(discover(self.queue, "token", repositories=["arthexis/gway-remote"], fetcher=fetch)["existing"], 1)

    def test_terminal_decision_is_not_rediscovered(self):
        issue = {"number": 37, "user": {"id": TRUSTED_CREATOR_ID, "login": "arthexis"}}
        fetch = lambda repo, token: iter([issue])
        discover(self.queue, "token", repositories=["arthexis/gway-remote"], fetcher=fetch)
        task = self.queue.list()[0]
        self.queue.transition(task["id"], "requested", "cancelled")
        self.assertEqual(discover(self.queue, "token", repositories=["arthexis/gway-remote"], fetcher=fetch)["existing"], 1)

    def test_repo_allowlist(self):
        with self.assertRaises(ValueError):
            discover(self.queue, "token", repositories=["attacker/repo"], fetcher=lambda *args: iter(()))


if __name__ == "__main__":
    unittest.main()
