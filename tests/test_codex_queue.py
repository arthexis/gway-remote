import tempfile
import unittest
from pathlib import Path
from gway_remote.codex_queue import TaskQueue


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.db"
        self.q = TaskQueue(self.path)

    def tearDown(self):
        self.q.close()
        self.temp.cleanup()

    def task(self):
        return self.q.request("field-validation", "arthexis/gway-remote", 35)

    def test_persistence_and_private_file(self):
        task = self.task()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.q.close()
        self.q = TaskQueue(self.path)
        self.assertEqual(self.q.get(task["id"])["state"], "requested")

    def test_lifecycle_and_invalid_transitions(self):
        tid = self.task()["id"]
        self.q.transition(tid, "requested", "queued")
        self.q.transition(tid, "queued", "running")
        self.q.transition(tid, "running", "succeeded")
        with self.assertRaises(ValueError):
            self.q.transition(tid, "succeeded", "running")

    def test_single_slot_across_connections(self):
        a, b = self.task()["id"], self.task()["id"]
        for tid in (a, b):
            self.q.transition(tid, "requested", "queued")
        with TaskQueue(self.path) as other:
            self.q.transition(a, "queued", "running")
            with self.assertRaises(ValueError):
                other.transition(b, "queued", "running")

    def test_recovery_does_not_retry(self):
        tid = self.task()["id"]
        self.q.transition(tid, "requested", "queued")
        self.q.transition(tid, "queued", "running")
        self.assertEqual(self.q.recover(), 1)
        self.assertEqual(self.q.get(tid)["state"], "interrupted")
        self.assertEqual(self.q.recover(), 0)

    def test_cancel_queued(self):
        tid = self.task()["id"]
        self.q.transition(tid, "requested", "queued")
        self.q.transition(tid, "queued", "cancelled")
        self.assertEqual(self.q.get(tid)["state"], "cancelled")

    def test_reject_invalid_request_and_limit(self):
        with self.assertRaises(ValueError):
            self.q.request("", "repo", 1)
        with self.assertRaises(ValueError):
            self.q.list(0)


if __name__ == "__main__":
    unittest.main()
