import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("backup_wrapper", Path(__file__).resolve().parents[2] / "scripts/backup-with-activity-feed.py")
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)

class BackupWrapperTests(TestCase):
    def test_verified_receipt_dedup_and_no_sensitive_output(self):
        stamp = "2026-11-24T10:00:00Z"
        lines = [wrapper.PASS, "Backup date: " + stamp, "private path"]
        first = wrapper.receipt(lines, 0, invocation="a", now=stamp)
        self.assertEqual(first, wrapper.receipt(lines, 0, invocation="b", now=stamp))
        runner = Mock(return_value=Mock(returncode=0))
        self.assertTrue(wrapper.emit(first, runner=runner))
        self.assertNotIn("private path", str(runner.call_args))
        self.assertIn("physical boot not attested", str(runner.call_args))

    def test_no_receipt_no_success(self):
        self.assertIsNone(wrapper.receipt([], 0, invocation="a", now="now"))
        self.assertEqual(wrapper.receipt([wrapper.PASS], 1, invocation="a", now="now"), ("failed", "a", "now"))
