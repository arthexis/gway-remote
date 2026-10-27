"""Inspection must reject unapproved nodes and untrusted registry material."""
import json
import os
import subprocess
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gway_remote.remote_inspection import inspect


class RemoteInspectionTests(unittest.TestCase):
    def test_unapproved_never_reads_files(self):
        with self.assertRaisesRegex(ValueError, "not approved"):
            inspect("gway-005", approved=set())

    def test_strict_bastion_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "ssh.conf"
            config.write_text("Host gway-004\n")
            config.chmod(0o600)
            snapshot = {"schema": 2, "generated_at": datetime.now(timezone.utc).isoformat(),
                        "nodes": [{"node": "gway-004", "address": "10.90.0.4/32",
                                   "state": "active"}]}
            effective = ("hostname 10.90.0.4\nstricthostkeychecking yes\n"
                         "batchmode yes\nuserknownhostsfile /etc/ssh/known_hosts\n")
            with patch("gway_remote.inspection_ssh_trust.validate_profile"), patch("gway_remote.watchtower_inspection_client.fetch_snapshot",
                       return_value=snapshot), patch(
                           "gway_remote.remote_inspection.subprocess.run",
                           return_value=subprocess.CompletedProcess([], 0, effective, "")
                       ), patch("gway_remote.remote_inspection.inspect_ssh",
                                return_value={"ssh": "verified"}) as ssh:
                result = inspect("gway-004", approved={"gway-004"}, ssh_config=config)
            self.assertEqual(result["ssh"], "verified")
            ssh.assert_called_once_with("gway-004", config=config)

    def test_untrusted_ssh_profile_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "ssh.conf"
            config.write_text("Host *\n")
            config.chmod(0o666)
            with self.assertRaises(ValueError):
                inspect("gway-004", approved={"gway-004"}, ssh_config=config)
