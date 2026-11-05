"""Watchtower key provisioning must never overwrite an existing identity."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.watchtower_attest import provision_host_key


class TestProvisionHostKey(unittest.TestCase):
    def test_creates_protected_file_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verified-gway-002-host.pub"
            with patch("gway_remote.watchtower_attest.host_key_path", return_value=path), \
                 patch("gway_remote.inspection_ssh_trust._trusted_parent_directories"), \
                 patch("gway_remote.watchtower_attest.validate_public_key", side_effect=lambda value: value):
                key = "ssh-ed25519 AAAATEST"
                self.assertEqual(provision_host_key("gway-002", key, dry_run=True), path)
                self.assertFalse(path.exists())
                self.assertEqual(provision_host_key("gway-002", key), path)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_text(), key + "\n")
                self.assertEqual(provision_host_key("gway-002", key), path)
                with self.assertRaises(ValueError):
                    provision_host_key("gway-002", "ssh-ed25519 DIFFERENT")
                self.assertEqual(path.read_text(), key + "\n")
