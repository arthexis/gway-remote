import sqlite3
import tempfile
import unittest
from pathlib import Path

from gway_remote.codex_queue import TaskQueue


class MigrationTests(unittest.TestCase):
    def test_legacy_database_preserves_rows_and_reopens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.db"
            db = sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE tasks (
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, repository TEXT NOT NULL,
                  issue INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN
                  ('requested','queued','running','succeeded','failed','cancelled','interrupted')),
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  detail TEXT NOT NULL DEFAULT '');
                CREATE UNIQUE INDEX single_running_task ON tasks(state) WHERE state='running';
                CREATE INDEX task_order ON tasks(state,created_at,id);
                INSERT INTO tasks VALUES
                  ('legacy', 'field-validation', 'arthexis/gway-remote', 35,
                   'requested', '2026-01-01', '2026-01-01', 'preserve this');
            """)
            db.close()
            for _ in range(2):
                with TaskQueue(path) as queue:
                    row = queue.get("legacy")
                    self.assertEqual(row["detail"], "preserve this")
                    self.assertEqual(row["priority"], "P2")
                    self.assertEqual(row["source"], "manual")
                    self.assertEqual(row["state"], "requested")
                    self.assertEqual(queue.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            with TaskQueue(path) as queue:
                queue.veto("legacy", "operator decision")
                self.assertEqual(queue.get("legacy")["state"], "vetoed")

    def test_new_database_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.db"
            with TaskQueue(path) as queue:
                task = queue.admit("field-validation", "arthexis/gway-remote", 35, source="github")
                self.assertEqual(task["source"], "github")
            with TaskQueue(path) as queue:
                self.assertEqual(queue.get(task["id"])["source"], "github")


if __name__ == "__main__":
    unittest.main()
