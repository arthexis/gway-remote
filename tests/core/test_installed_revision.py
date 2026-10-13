"""Installed revision is independent of attempted journal SHA."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gway_remote.status import installed_revision


class InstalledRevisionTests(unittest.TestCase):
    def test_installed_csms_release_is_read_from_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            version = home / ".local/share/ocpp-csms/releases" / ("a" * 12)
            version.mkdir(parents=True)
            (home / ".local/share/ocpp-csms/current").symlink_to(version)
            with patch("pathlib.Path.home", return_value=home):
                self.assertEqual(installed_revision("ocpp-csms"), "a" * 12)
                self.assertIsNone(installed_revision("ocpp-simulator"))

    def test_invalid_or_missing_link_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            location = home / ".local/share/ocpp-csms"
            location.mkdir(parents=True)
            (location / "current").symlink_to(location / "releases/missing")
            with patch("pathlib.Path.home", return_value=home):
                self.assertIsNone(installed_revision("ocpp-csms"))
