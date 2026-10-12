"""Architecture checks for opt-in mobile API hosting."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class HostingTests(unittest.TestCase):
    def test_unit_stays_on_loopback_and_unprivileged(self):
        unit = (ROOT / "deploy/systemd/user/gway-remote-mobile-api.service").read_text()
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("EnvironmentFile=%h/.config/gway-remote/mobile-api.env", unit)
        self.assertNotIn("ExecStartPre=", unit)
        self.assertNotIn("sudo ", unit)

    def test_installer_does_not_start_or_enable_service(self):
        script = (ROOT / "scripts/install-mobile-api.sh").read_text()
        self.assertIn("chmod 600", script)
        self.assertIn("chmod 700", script)
        self.assertIn("if [ ! -e", script)
        self.assertNotIn("systemctl --user start ", script)
        self.assertNotIn("systemctl --user enable ", script.split('echo "Review network access')[0])
        self.assertNotIn("printf '%s\\n' \"$TOKEN\"", script)


if __name__ == "__main__":
    unittest.main()
