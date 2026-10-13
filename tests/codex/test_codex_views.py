import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from gway_remote.codex_queue import TaskQueue
from gway_remote.codex_views import list_tasks, task_detail
from gway_remote.mobile import commands, execute

class CodexViewsTests(unittest.TestCase):
    def test_read_only_views(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "queue.sqlite"
            with TaskQueue(db) as q:
                task = q.request("field-validation", "arthexis/gway-remote", 71)
                q.transition(task["id"], "requested", "queued")
                q.transition(task["id"], "queued", "running")
                q.start_execution(task["id"])
                q.finish_execution(task["id"], "succeeded", "done", exit_code=0)
            self.assertEqual(list_tasks(db=db)["tasks"][0]["task"]["id"], task["id"])
            result = task_detail(task["id"], db=db)
            self.assertEqual(result["execution"]["exit_code"], 0)
            self.assertEqual(result["execution"]["artifacts"], [])
    def test_validation(self):
        with self.assertRaisesRegex(ValueError, "invalid_task_id"):
            task_detail("../../etc/passwd")
        with self.assertRaisesRegex(ValueError, "invalid_limit"):
            list_tasks(501)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "task_not_found"):
                task_detail(str(uuid4()), db=Path(temp) / "tasks.sqlite")
    def test_mobile_commands_read_only(self):
        found = {c["name"]: c for c in commands()}
        self.assertTrue(found["codex-tasks"]["read_only"])
        self.assertTrue(found["codex-task"]["read_only"])
        with self.assertRaisesRegex(ValueError, "invalid_arguments"):
            execute("codex-tasks", {"extra": True})
        with self.assertRaisesRegex(ValueError, "invalid_arguments"):
            execute("codex-task", {"task_id": "a", "extra": True})
