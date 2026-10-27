"""Regression tests for bounded read-only remote revision probes."""
import subprocess
import unittest
from unittest.mock import Mock

from gway_remote.inspection_revisions import inspect_revisions


class InspectionRevisionTests(unittest.TestCase):
    def test_reports_sha_only_from_release_directory(self):
        runner = Mock(side_effect=[
            subprocess.CompletedProcess([], 0, "/home/arthe/.local/share/ocpp-csms/releases/0123456789abcdef0123456789abcdef01234567\n", ""),
            subprocess.CompletedProcess([], 0, "/tmp/unknown\n", ""),
        ])
        rows = inspect_revisions("gway-004", "/tmp/ssh.conf", runner=runner)
        self.assertEqual(rows[0]["installed_sha"], "0123456789abcdef0123456789abcdef01234567")
        self.assertIsNone(rows[1]["installed_sha"])
        for call in runner.call_args_list:
            args = call.args[0]
            self.assertEqual(args[0], "ssh")
            self.assertEqual(args[-3], "readlink")
            self.assertEqual(args[-2], "-f")
            self.assertNotIn("sudo", args)
            self.assertNotIn("systemctl restart", " ".join(args))

    def test_failed_probe_is_unknown(self):
        runner = Mock(side_effect=OSError("connection refused"))
        rows = inspect_revisions("gway-004", "/tmp/ssh.conf", runner=runner)
        self.assertTrue(all(row["installed_sha"] is None for row in rows))

    def test_non_revision_is_not_accepted(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "/x/releases/latest\n", ""))
        self.assertTrue(all(row["evidence"] == "unknown" for row in
                            inspect_revisions("gway-004", "/tmp/ssh.conf", runner=runner)))
