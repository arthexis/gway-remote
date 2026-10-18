"""RFID monitoring must reflect service state and active release, not attempt journal."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.health import component_health, quick_component_check
from gway_remote.status import installed_revision


class RfidMonitoringTests(unittest.TestCase):
    @patch("gway_remote.health._command")
    def test_healthy_requires_active_and_enabled_system_service(self, command):
        command.side_effect = [True, True]
        self.assertTrue(component_health("gway-rfid"))
        self.assertEqual(command.call_args_list[0].args[0],
                         ["systemctl", "is-active", "--quiet", "gway-rfid.service"])
        self.assertEqual(command.call_args_list[1].args[0],
                         ["systemctl", "is-enabled", "--quiet", "gway-rfid.service"])
        command.reset_mock()
        command.side_effect = [False]
        self.assertFalse(component_health("gway-rfid"))
        self.assertEqual(command.call_count, 1)

    def test_release_full_sha_and_missing_link(self):
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / ".local/share/gway-rfid"
            release = root / "releases" / sha
            release.mkdir(parents=True)
            with patch("pathlib.Path.home", return_value=home):
                self.assertIsNone(installed_revision("gway-rfid"))
                self.assertEqual(quick_component_check("gway-rfid"), "release-missing")
                (root / "current").symlink_to(release, target_is_directory=True)
                self.assertEqual(installed_revision("gway-rfid"), sha)
                self.assertEqual(quick_component_check("gway-rfid"), "release-present")
                (root / "current").unlink()
                (root / "current").symlink_to(root / "releases" / "missing")
                self.assertIsNone(installed_revision("gway-rfid"))

    def test_revision_rejects_untrusted_release_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / ".local/share/gway-rfid"
            release = root / "releases" / "not-a-sha"
            release.mkdir(parents=True)
            (root / "current").symlink_to(release, target_is_directory=True)
            with patch("pathlib.Path.home", return_value=home):
                self.assertIsNone(installed_revision("gway-rfid"))


if __name__ == "__main__":
    unittest.main()
