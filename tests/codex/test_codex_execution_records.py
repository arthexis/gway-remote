"""2C3a: durable structured executor results and legacy migration."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gway_remote.codex_queue import TaskQueue


class ExecutionRecordTests(unittest.TestCase):
    def test_persist_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.sqlite"
            with TaskQueue(path) as queue:
                task = queue.request("field-validation", "arthexis/gway-remote", 41)
                queue.transition(task["id"], "requested", "queued")
                queue.transition(task["id"], "queued", "running")
                queue.start_execution(task["id"], workspace="/tmp/work",
                                      transcript="/tmp/log", final_message="/tmp/final")
                queue.finish_execution(task["id"], "succeeded", "finished", exit_code=0)
            with TaskQueue(path) as queue:
                record = queue.execution(task["id"])
                self.assertEqual(record["exit_code"], 0)
                self.assertEqual(record["outcome"], "succeeded")
                self.assertEqual(record["workspace_path"], "/tmp/work")
                self.assertIsNotNone(record["finished_at"])
                self.assertEqual(queue.get(task["id"])["state"], "succeeded")

    def test_recovery_marks_execution_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TaskQueue(Path(tmp) / "tasks.sqlite") as queue:
                task = queue.request("field-validation", "arthexis/gway-remote", 41)
                queue.transition(task["id"], "requested", "queued")
                queue.transition(task["id"], "queued", "running")
                queue.start_execution(task["id"])
                self.assertEqual(queue.recover(), 1)
                self.assertEqual(queue.execution(task["id"])["outcome"], "interrupted")

    def test_legacy_tasks_table_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.sqlite"
            with TaskQueue(path) as queue:
                task = queue.request("field-validation", "arthexis/gway-remote", 41)
            with TaskQueue(path) as queue:
                self.assertIsNone(queue.execution(task["id"]))
                self.assertEqual(queue.get(task["id"])["state"], "requested")
