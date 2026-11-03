"""Regression checks for adopt settings and public-key inspection."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.watchtower_settings import adopt_settings
from gway_remote.wireguard_identity import public_key


KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class AdoptSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "watchtower.json"
        self.path.write_text(json.dumps({
            "ledger": "/var/lib/gway-remote/watchtower/ledger.sqlite3",
            "network": "10.90.0.0/24",
            "gateway": "10.90.0.1",
            "public_url": "https://register.gelectriic.com",
        }))
        self.path.chmod(0o600)

    def test_defaults_and_explicit_config(self):
        info = self.path.stat()
        from unittest.mock import Mock
        with patch.object(Path, "stat", autospec=True, side_effect=lambda path, *a, **kw:
                          Mock(st_uid=0, st_mode=0o100600) if str(path) == str(self.path)
                          else info):
            cfg = adopt_settings(self.path)
            self.assertEqual(cfg["gateway"], "10.90.0.1")
            self.assertEqual(cfg["config"], "/etc/wireguard/gway.conf")
            data = json.loads(self.path.read_text())
            data["wireguard_config"] = "/etc/wireguard/custom.conf"
            self.path.write_text(json.dumps(data))
            self.assertEqual(adopt_settings(self.path)["config"], "/etc/wireguard/custom.conf")

    def test_group_readable_or_symlink_settings_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(PermissionError, "0600"):
            adopt_settings(self.path)
        self.path.chmod(0o600)
        alias = self.path.with_name("alias.json")
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            adopt_settings(alias)

    def test_missing_required_settings_rejected(self):
        self.path.write_text(json.dumps({"network": "10.90.0.0/24"}))
        with self.assertRaises((PermissionError, ValueError)):
            adopt_settings(self.path)


class PublicKeyTests(unittest.TestCase):
    def test_public_key_command_uses_only_safe_wg_show(self):
        seen = []
        def runner(argv, **kw):
            seen.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0, stdout=KEY + "\n")
        self.assertEqual(public_key(runner=runner), KEY)
        self.assertEqual(seen[0][0], ["wg", "show", "gway", "public-key"])
        self.assertTrue(seen[0][1]["check"])

    def test_invalid_public_key_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            public_key(runner=lambda *a, **kw:
                       subprocess.CompletedProcess(a[0], 0, stdout="(hidden)\n"))

    def test_alternate_interface_denied(self):
        with self.assertRaises(ValueError):
            public_key("other")


if __name__ == "__main__":
    unittest.main()
