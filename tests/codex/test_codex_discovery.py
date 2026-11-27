import tempfile
import unittest
from pathlib import Path
from gway_remote.codex_queue import TaskQueue
from gway_remote.codex_discovery import discover


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = TaskQueue(Path(self.tmp.name) / "queue.db")
        self.repo = "arthexis/gway-remote"

    def tearDown(self):
        self.queue.close()
        self.tmp.cleanup()

    def test_no_second_automatic_queue(self):
        def fetch(*args):
            raise AssertionError("legacy discovery must not enumerate new assignments")
        result = discover(self.queue, "token", repositories=[self.repo], fetcher=fetch)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(self.queue.list(), [])

    def test_reconciliation_preserves_open_import_and_manual_tasks(self):
        self.queue.admit("field-validation", self.repo, 37, source="github")
        self.queue.admit("field-validation", self.repo, 99)
        result = discover(self.queue, "token", repositories=[self.repo],
                          verifier=lambda *args: False)
        self.assertEqual(result["withdrawn"], 0)
        self.assertEqual(len(self.queue.list()), 2)
        result = discover(self.queue, "token", repositories=[self.repo],
                          verifier=lambda *args: True)
        self.assertEqual(result["withdrawn"], 1)
        by_issue = {t["issue"]: t["state"] for t in self.queue.list()}
        self.assertEqual(by_issue[37], "cancelled")
        self.assertEqual(by_issue[99], "requested")

    def test_failed_verification_preserves_task(self):
        self.queue.admit("field-validation", self.repo, 37, source="github")
        def unavailable(*args):
            raise TimeoutError("GitHub unavailable")
        result = discover(self.queue, "token", repositories=[self.repo], verifier=unavailable)
        self.assertEqual(result["withdrawn"], 0)
        self.assertEqual(self.queue.list()[0]["state"], "requested")

    def test_repo_allowlist(self):
        with self.assertRaises(ValueError):
            discover(self.queue, "token", repositories=["attacker/repo"])


if __name__ == "__main__":
    unittest.main()
