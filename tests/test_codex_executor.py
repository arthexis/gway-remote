"""Executor tests do not invoke real Codex or access GitHub."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.codex_queue import TaskQueue
from gway_remote.codex_executor import run_once


class ExecutorTests(unittest.TestCase):
    def test_unapproved_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "tasks.sqlite"
            with TaskQueue(db) as queue:
                queue.admit("field-validation", "arthexis/gway-remote", 41)
            with patch("gway_remote.codex_executor.subprocess.run") as launch:
                self.assertIsNone(run_once(db=db, token="test"))
                launch.assert_not_called()

    def test_missing_token_fails_claim_without_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "tasks.sqlite"
            with TaskQueue(db) as queue:
                task = queue.admit("field-validation", "arthexis/gway-remote", 41)
                queue.approve(task["id"])
            with patch("gway_remote.codex_executor.subprocess.run") as launch:
                result = run_once(db=db, token="")
                self.assertEqual(result["state"], "failed")
                launch.assert_not_called()

    def test_codex_exit_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "tasks.sqlite"
            checkout = root / "Repos" / "gway-remote"
            checkout.mkdir(parents=True)
            (checkout / ".git").mkdir()
            with TaskQueue(db) as queue:
                task = queue.admit("field-validation", "arthexis/gway-remote", 41)
                queue.approve(task["id"])
            class Result:
                returncode = 0
            with patch("gway_remote.codex_executor.issue_objective", return_value="objective"), \
                 patch("gway_remote.codex_executor.subprocess.run", return_value=Result()) as launch:
                result = run_once(db=db, token="test", repos_root=root / "Repos",
                                  work_root=root / "work")
            self.assertEqual(result["state"], "succeeded")
            self.assertEqual(launch.call_count, 2)
            self.assertEqual(launch.call_args_list[-1].args[0][0:2], ["codex", "exec"])
