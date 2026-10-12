"""Worker foundation tests; never invokes Codex."""
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from gway_remote import codex_worker


class CodexWorkerTests(unittest.TestCase):
    def test_status_reports_executor_enabled(self):
        with patch.object(codex_worker, "codex_available", return_value=True):
            value = codex_worker.status(time.monotonic() - 5)
        self.assertEqual(value["state"], "idle")
        self.assertTrue(value["codex_available"])
        self.assertTrue(value["task_execution_enabled"])
        self.assertGreaterEqual(value["uptime_seconds"], 5)

    def test_executing_status_exposes_task(self):
        with patch.object(codex_worker, "codex_available", return_value=True):
            value = codex_worker.status(time.monotonic(), executing=True, task_id="task-42")
        self.assertEqual(value["state"], "executing")
        self.assertEqual(value["active_task_id"], "task-42")
        self.assertTrue(value["task_execution_enabled"])

    def test_default_socket_uses_runtime_dir(self):
        with patch.dict("os.environ", {"XDG_RUNTIME_DIR": "/run/user/1000"}):
            self.assertEqual(str(codex_worker.default_socket()), "/run/user/1000/gway-codex-worker.sock")


if __name__ == "__main__":
    unittest.main()
