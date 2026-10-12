"""2C2 process lifecycle tests using a fake executable."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.codex_executor import run_once
from gway_remote.codex_queue import TaskQueue


class LifecycleTests(unittest.TestCase):
    def test_shutdown_interrupts_running_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "tasks.db"
            checkout = root / "Repos" / "gway-remote"
            checkout.mkdir(parents=True)
            (checkout / ".git").mkdir()
            with TaskQueue(db) as queue:
                task = queue.admit("field-validation", "arthexis/gway-remote", 41)
                queue.approve(task["id"])
            stopped = threading.Event()
            stopped.set()
            class FakeProcess:
                pid = 123
                returncode = -15
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return -15
            with patch("gway_remote.codex_executor.issue_objective", return_value="objective"), \
                 patch("gway_remote.codex_executor.subprocess.run"), \
                 patch("gway_remote.codex_executor.subprocess.Popen", return_value=FakeProcess()), \
                 patch("gway_remote.codex_executor.os.killpg") as kill:
                result = run_once(db=db, token="test", repos_root=root / "Repos",
                                  work_root=root / "work", stop=stopped)
            self.assertEqual(result["state"], "interrupted")
            kill.assert_called_once()

    def test_timeout_must_be_positive(self):
        with self.assertRaises(ValueError):
            run_once(timeout_seconds=-1)

    def test_process_disappears_before_termination_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "tasks.db"
            checkout = root / "Repos" / "gway-remote"
            checkout.mkdir(parents=True)
            (checkout / ".git").mkdir()
            with TaskQueue(db) as queue:
                task = queue.admit("field-validation", "arthexis/gway-remote", 41)
                queue.approve(task["id"])
            stopped = threading.Event()
            stopped.set()
            class Process:
                pid = 123
                returncode = 0
                def poll(self):
                    return None
                def wait(self, timeout=None):
                    return 0
            with patch("gway_remote.codex_executor.issue_objective", return_value="objective"), \
                 patch("gway_remote.codex_executor.subprocess.run"), \
                 patch("gway_remote.codex_executor.subprocess.Popen", return_value=Process()), \
                 patch("gway_remote.codex_executor.os.killpg", side_effect=ProcessLookupError):
                result = run_once(db=db, token="test", repos_root=root / "Repos",
                                  work_root=root / "work", stop=stopped)
            self.assertEqual(result["state"], "interrupted")
