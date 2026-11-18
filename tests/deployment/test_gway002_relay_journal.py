"""Hermetic crash-recovery checks. Never touches real SSH or privileged paths."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "ansible/playbooks/gway002_relay_journal.py"
spec = importlib.util.spec_from_file_location("gway002_relay_journal", SCRIPT)
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class RecoveryJournalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.patches = [
            patch.object(journal, "ROOT", base / "backup"),
            patch.object(journal, "JOURNAL", base / "backup/journal.json"),
            patch.object(journal, "PATHS", tuple(base / name for name in ("sshd", "sudoers", "key"))),
            patch.object(journal, "_parents", lambda path: None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        journal.ROOT.mkdir(mode=0o700)
        self.files = journal.PATHS
        self.files[0].write_bytes(b"original\x00bytes\n")
        self.files[0].chmod(0o644)
        self.files[1].write_bytes(b"old sudoers\n")
        self.files[1].chmod(0o440)

    def test_power_loss_then_explicit_byte_exact_recovery(self):
        journal.prepare()
        self.files[0].write_bytes(b"partial update")
        self.files[1].write_bytes(b"other update")
        self.files[2].write_bytes(b"new key")
        journal.recover()
        self.assertEqual(self.files[0].read_bytes(), b"original\x00bytes\n")
        self.assertEqual(self.files[1].read_bytes(), b"old sudoers\n")
        self.assertFalse(self.files[2].exists())
        self.assertEqual(self.files[1].stat().st_mode & 0o777, 0o440)
        journal.recover()  # Interruption during restoration is replay-safe.
        journal.finish()
        self.assertEqual(journal._journal()["state"], "complete")
        with self.assertRaises(RuntimeError):
            journal.recover()

    def test_no_second_prepare_after_unresolved_crash(self):
        journal.prepare()
        with self.assertRaises(RuntimeError):
            journal.prepare()
        self.assertEqual(journal._journal()["state"], "pending")

    def test_corrupted_backup_refuses_restore(self):
        journal.prepare()
        record = journal._journal()
        record["files"][str(self.files[0])]["sha256"] = "0" * 64
        journal._write_journal(record)
        with self.assertRaisesRegex(RuntimeError, "backup checksum mismatch"):
            journal.recover()
        self.assertEqual(journal._journal()["state"], "pending")

    def test_symlink_prevents_overwrite(self):
        journal.prepare()
        self.files[0].unlink()
        self.files[0].symlink_to(self.files[1])
        with self.assertRaisesRegex(RuntimeError, "unsafe relay file"):
            journal.recover()
        self.assertTrue(self.files[0].is_symlink())
        self.assertEqual(journal._journal()["state"], "pending")


if __name__ == "__main__":
    unittest.main()
