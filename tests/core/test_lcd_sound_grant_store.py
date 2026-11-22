"""File ownership/symlink/security checks for source grants."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from gway_remote.lcd_sound_grant_store import load_operator_grants


class GrantStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "grants.json"
        self.owner = os.geteuid()

    def write(self, value=None):
        self.path.write_text(json.dumps(value if value is not None else {
            "schema": 1, "grants": {"auth:abb": {
                "source": "ocpp-abb-1", "enabled": True,
                "targets": ["gway-001"], "operations": ["sound.play"]
            }}}))
        self.path.chmod(0o600)

    def test_load_private_file(self):
        self.write()
        self.assertIn("auth:abb", load_operator_grants(
            self.path, expected_owner=self.owner))

    def test_writable_snapshot_rejected(self):
        self.write()
        self.path.chmod(0o666)
        with self.assertRaises(PermissionError):
            load_operator_grants(self.path, expected_owner=self.owner)

    def test_symlink_snapshot_rejected(self):
        self.write()
        link = self.path.with_name("link.json")
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            load_operator_grants(link, expected_owner=self.owner)

    def test_writable_parent_directory_rejected(self):
        self.write()
        parent = self.path.parent
        before = parent.stat().st_mode & 0o777
        try:
            parent.chmod(0o777)
            with self.assertRaises(PermissionError):
                load_operator_grants(self.path, expected_owner=self.owner)
        finally:
            parent.chmod(before)

    def test_wrong_owner_rejected(self):
        self.write()
        with self.assertRaises(PermissionError):
            load_operator_grants(self.path, expected_owner=self.owner + 1)

    def test_invalid_schema_rejected(self):
        self.write({"schema": True, "grants": {}})
        with self.assertRaises(ValueError):
            load_operator_grants(self.path, expected_owner=self.owner)

    def test_oversized_snapshot_rejected(self):
        self.write({"schema": 1, "grants": {"a": "x" * 18000}})
        with self.assertRaises(PermissionError):
            load_operator_grants(self.path, expected_owner=self.owner)

    def test_missing_grant_registry_rejected(self):
        self.write({"schema": 1})
        with self.assertRaises(ValueError):
            load_operator_grants(self.path, expected_owner=self.owner)
