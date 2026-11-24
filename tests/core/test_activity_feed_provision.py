"""Provisioning must be hermetic; no systemd or real home access."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("feed_provision", ROOT / "scripts/provision-activity-feed.py")
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


class FeedProvisionTests(unittest.TestCase):
    def test_repeat_install_and_owned_upgrade(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            units = ROOT / "deploy/systemd"
            self.assertEqual(provision.provision(home, units), 3)
            alias = home / ".local/bin/feed"
            before = alias.stat().st_mtime_ns
            self.assertEqual(provision.provision(home, units), 0)
            self.assertEqual(alias.stat().st_mtime_ns, before)
            self.assertEqual(alias.stat().st_mode & 0o777, 0o755)

    def test_unrelated_alias_fails_without_unit_writes(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            alias = home / ".local/bin/feed"
            alias.parent.mkdir(parents=True)
            alias.write_text("unrelated")
            with self.assertRaises(PermissionError):
                provision.provision(home, ROOT / "deploy/systemd")
            self.assertEqual(alias.read_text(), "unrelated")
            self.assertFalse((home / ".config/systemd/user").exists())
