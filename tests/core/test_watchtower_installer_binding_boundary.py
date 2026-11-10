"""Fail-closed Watchtower installer binding: no untrusted execute.json identity."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import watchtower_exec_service as service


class InstallerBindingBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "execute.json"
        self.entry = {
            "node": "gway-001", "address": "10.6.0.2",
            "ssh_host_alias": "gway-001", "known_hosts": "/missing/known_hosts",
            "identity_file": "/missing/key", "host_key_sha256": "a" * 64,
        }
        self.inventory = {"nodes": [{
            "node": "gway-001", "registered": True, "identity_verified": True,
            "address": "10.6.0.2", "execute_eligible": True,
            "reachable": "reachable",
        }]}

    def load(self, entry=None, inventory=None):
        self.config.write_text(json.dumps({"enabled": True, "nodes": [entry or self.entry]}))
        with patch.object(service.node_registry_inventory, "load",
                          return_value=inventory or self.inventory), patch.object(
                          service.Path, "lstat", autospec=True) as lstat:
            original = Path.lstat
            # Only the trusted config ownership is simulated; no SSH is attempted.
            from types import SimpleNamespace
            import stat
            lstat.return_value = SimpleNamespace(st_mode=stat.S_IFREG | 0o600,
                                                   st_uid=0, st_size=self.config.stat().st_size)
            return service.load_service(self.config)

    def test_missing_attested_installer_denied(self):
        with self.assertRaisesRegex(PermissionError, "attested installer"):
            self.load()

    def test_config_cannot_select_installer(self):
        with self.assertRaisesRegex(ValueError, "pinned node entry"):
            self.load({**self.entry, "installer_user": "attacker"})

    def test_unverified_or_rotated_host_denied(self):
        for change in ({"identity_verified": False}, {"execute_eligible": False},
                       {"address": "10.6.0.3"}, {"reachable": "unknown"}):
            with self.subTest(change=change), self.assertRaises(PermissionError):
                self.load(inventory={"nodes": [{**self.inventory["nodes"][0], **change}]})

    def test_invalid_inventory_installer_denied(self):
        for user in ("root", "a;id", "", 3):
            with self.subTest(user=user), self.assertRaises(PermissionError):
                self.load(inventory={"nodes": [{**self.inventory["nodes"][0],
                                                 "installer_user": user}]})


if __name__ == "__main__":
    unittest.main()
