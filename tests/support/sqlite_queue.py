"""Isolated, automatically cleaned up SQLite task queue fixture."""
import tempfile
import unittest
from pathlib import Path
from gway_remote.codex_queue import TaskQueue


class QueueCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "tasks.db"
        self.q = TaskQueue(self.path)
        self.addCleanup(self.q.close)
