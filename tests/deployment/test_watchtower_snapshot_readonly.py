"""No-write Watchtower inspection regression tests."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.node_inspection import snapshot_from_path
from gway_remote.watchtower_inspection_command import main


class ReadOnlySnapshotTests(unittest.TestCase):
    def test_wal_snapshot_does_not_modify_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.sqlite3"
            writer = sqlite3.connect(path)
            try:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("CREATE TABLE devices (device TEXT, address TEXT, state TEXT)")
                writer.commit()
                writer.execute("INSERT INTO devices VALUES ('gway-004','10.10.0.4/32','active')")
                writer.commit()
                before = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                          for p in Path(folder).iterdir()}
                with patch("gway_remote.watchtower_enrollment.Ledger.__init__",
                           side_effect=AssertionError("Ledger must not be initialized")):
                    result = snapshot_from_path(path)
                self.assertEqual(result["nodes"][0]["node"], "gway-004")
                after = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                         for p in Path(folder).iterdir()}
                self.assertEqual(before, after)
            finally:
                writer.close()

    def test_missing_ledger_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.db"
            with self.assertRaises(ValueError):
                snapshot_from_path(path)
            self.assertFalse(path.exists())

    def test_forced_command_rejects_other_operations(self):
        with patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "bash"}):
            with self.assertRaises(SystemExit):
                main()
