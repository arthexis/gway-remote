import tempfile
import unittest
from pathlib import Path
from gway_remote.codex_queue import TaskQueue


class PriorityTests(unittest.TestCase):
    def test_approval_priority_and_single_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TaskQueue(Path(tmp) / "tasks.db") as queue:
                low = queue.admit("field-validation", "arthexis/gway-remote", 301, "P3")
                high = queue.admit("field-validation", "arthexis/gway-remote", 302, "P0")
                self.assertIsNone(queue.next())
                queue.approve(low["id"])
                queue.approve(high["id"])
                self.assertEqual(queue.next()["id"], high["id"])
                self.assertEqual(queue.claim_next()["id"], high["id"])
                self.assertIsNone(queue.claim_next())
                self.assertEqual(queue.next()["id"], low["id"])
                queue.transition(high["id"], "running", "succeeded")
                self.assertEqual(queue.claim_next()["id"], low["id"])

    def test_veto_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TaskQueue(Path(tmp) / "tasks.db") as queue:
                task = queue.admit("field-validation", "arthexis/gway-remote", 303)
                queue.veto(task["id"], "not approved")
                self.assertIsNone(queue.next())
                with self.assertRaises(ValueError):
                    queue.approve(task["id"])
