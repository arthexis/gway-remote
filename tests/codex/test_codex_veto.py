import tempfile
import unittest
from pathlib import Path
from gway_remote.codex_queue import TaskQueue

class VetoTests(unittest.TestCase):
    def test_veto_and_unveto(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tasks.db'
            with TaskQueue(path) as queue:
                task = queue.admit('field-validation', 'arthexis/gway-remote', 37)
                queue.veto(task['id'], 'Not approved')
            with TaskQueue(path) as queue:
                self.assertEqual(queue.get(task['id'])['state'], 'vetoed')
                self.assertEqual(queue.unveto(task['id'])['state'], 'requested')
