"""Installed identity is the sole authority for local execution."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import node_exec_identity as identity


class InstallationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "identity.json"

    def selected(self, value, *, owner=0, mode=None):
        self.path.write_text(json.dumps(value))
        if mode is not None:
            self.path.chmod(mode)
        original = Path.lstat

        def metadata(path):
            info = original(path)
            if Path(path) == self.path:
                return SimpleNamespace(st_mode=info.st_mode, st_uid=owner,
                                       st_size=info.st_size)
            return info

        with patch.object(Path, "lstat", autospec=True, side_effect=metadata), patch.object(
            identity.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1234, pw_dir="/home/installer")
        ):
            return identity.selected_user(self.path)

    def test_arbitrary_existing_installer_account_is_accepted(self):
        self.assertEqual(self.selected({"user": "installer"}), "installer")

    def test_missing_record_fails_closed(self):
        with self.assertRaises(FileNotFoundError):
            identity.selected_user(self.path)

    def test_root_or_invalid_record_is_rejected(self):
        for value in ({"user": "root"}, {"user": ""}, {"user": 12},
                      {"user": "installer", "override": "other"}, {}):
            with self.subTest(value=value), self.assertRaises((ValueError, PermissionError)):
                self.selected(value)

    def test_untrusted_ownership_and_permissions_rejected(self):
        with self.assertRaises(PermissionError):
            self.selected({"user": "installer"}, owner=1234)
        with self.assertRaises(PermissionError):
            self.selected({"user": "installer"}, mode=0o666)

    def test_cannot_override_identity_through_environment(self):
        with patch.object(identity, "selected_user", return_value="installer"), patch.object(
            identity.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1234, pw_dir="/home/installer")
        ), patch.object(identity.os, "geteuid", return_value=1234), patch.dict(
            os.environ, {"SSH_AUTH_SOCK": "/tmp/untrusted", "USER": "attacker"}
        ):
            env = identity.command_environment()
            self.assertEqual(env["USER"], "installer")
            self.assertNotIn("SSH_AUTH_SOCK", env)
            with self.assertRaises(PermissionError):
                identity.command_environment("attacker")


if __name__ == "__main__":
    unittest.main()
