"""Execution-account cutover preflight: no root, live SSH or services required."""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/verify-exec-cutover.py"
spec = importlib.util.spec_from_file_location("exec_cutover_preflight", SOURCE)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class CutoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.db = self.state / "jobs.sqlite3"

    def ledger(self, *states):
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE jobs (status TEXT NOT NULL)")
            for state in states:
                db.execute("INSERT INTO jobs VALUES (?)", (state,))

    def check(self, previous="gway-exec", requested="arthe", uid=0):
        with (patch.object(preflight.os, "geteuid", return_value=uid),
              patch.object(preflight, "selected_user", return_value=previous),
              patch.object(preflight, "state_dir", return_value=self.state),
              patch.object(sys, "argv", ["verify-exec-cutover.py", requested])):
            preflight.main()

    def test_completed_jobs_preserved_and_cutover_allowed(self):
        self.ledger("succeeded", "failed", "unknown", "cancelled", "timed_out")
        self.check()
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 5)

    def test_active_jobs_block_switch(self):
        for status in ("queued", "running"):
            with self.subTest(status=status):
                if self.db.exists():
                    self.db.unlink()
                self.ledger("succeeded", status)
                with self.assertRaisesRegex(SystemExit, "active jobs"):
                    self.check()

    def test_missing_ledger_allows_new_account_without_creation(self):
        self.check()
        self.assertFalse(self.db.exists())

    def test_invalid_ledger_and_symlink_fail_closed(self):
        self.db.write_text("not a database")
        with self.assertRaisesRegex(SystemExit, "cannot validate"):
            self.check()
        self.db.unlink()
        self.db.symlink_to(self.state / "missing")
        with self.assertRaisesRegex(SystemExit, "unsafe"):
            self.check()

    def test_only_root_can_authorize_identity_cutover(self):
        with self.assertRaisesRegex(SystemExit, "root"):
            self.check(uid=1000)

    def test_unrecognized_identity_never_selected(self):
        with self.assertRaisesRegex(SystemExit, "unsupported"):
            self.check(requested="root")


if __name__ == "__main__":
    unittest.main()
