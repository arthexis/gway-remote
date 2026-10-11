import sqlite3
import tempfile
import unittest
from pathlib import Path

from gway_remote.codex_queue import TaskQueue
from gway_remote.codex_policy import DEFAULT_PRIORITY, validate_request, verify_issue_creator, TRUSTED_CREATOR_ID


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.sqlite3"
        self.queue = TaskQueue(self.path)

    def tearDown(self):
        self.queue.close()
        self.temp.cleanup()

    def test_github_creator_must_match_verified_account(self):
        issue = {"user": {"id": TRUSTED_CREATOR_ID, "login": "arthexis"}}
        self.assertTrue(verify_issue_creator(issue, trusted_id=TRUSTED_CREATOR_ID))
        for author in (
            {"id": 999, "login": "arthexis"},
            {"id": TRUSTED_CREATOR_ID, "login": "someone-else"},
            {"login": "arthexis"},
            {"id": "780437", "login": "arthexis"},
        ):
            with self.subTest(author=author):
                self.assertFalse(verify_issue_creator({"user": author}, trusted_id=TRUSTED_CREATOR_ID))
        self.assertFalse(verify_issue_creator({**issue, "pull_request": {}}, trusted_id=TRUSTED_CREATOR_ID))
        self.assertFalse(verify_issue_creator(issue, trusted_id=0))

    def test_default_priority_and_requested_only(self):
        task = self.queue.admit("field-validation", "arthexis/gway-remote", 37)
        self.assertEqual(task["priority"], "P2")
        self.assertEqual(task["state"], "requested")

    def test_explicit_priority_is_metadata_only(self):
        task = self.queue.admit("read-only-inspection", "arthexis/ocpp-csms", 45, "P0")
        self.assertEqual(task["priority"], "P0")
        self.assertEqual(task["state"], "requested")

    def test_reject_unsafe_requests(self):
        for kind, repo, issue, priority in (
            ("deploy", "arthexis/gway-remote", 1, "P2"),
            ("field-validation", "other/repo", 1, "P2"),
            ("field-validation", "arthexis/gway-remote", 0, "P2"),
            ("field-validation", "arthexis/gway-remote", True, "P2"),
            ("field-validation", "arthexis/gway-remote", 1, "P9"),
        ):
            with self.subTest(kind=kind, repo=repo, issue=issue, priority=priority):
                with self.assertRaises(ValueError):
                    self.queue.admit(kind, repo, issue, priority)
        self.assertEqual(self.queue.list(), [])

    def test_active_duplicates_across_connections(self):
        a = self.queue.admit("field-validation", "arthexis/gway-remote", 37)
        with TaskQueue(self.path) as second:
            with self.assertRaises(ValueError):
                second.admit("field-validation", "arthexis/gway-remote", 37)
        self.queue.transition(a["id"], "requested", "cancelled")
        self.assertEqual(self.queue.admit("field-validation", "arthexis/gway-remote", 37)["state"], "requested")

    def test_upgrade_existing_part_a_database(self):
        self.queue.close()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP INDEX active_task_identity")
            db.execute("ALTER TABLE tasks DROP COLUMN priority")
        self.queue = TaskQueue(self.path)
        self.assertEqual(self.queue.admit("field-validation", "arthexis/gway-remote", 35)["priority"], "P2")


if __name__ == "__main__":
    unittest.main()
