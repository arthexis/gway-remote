"""Reports appliance deployment adapter regression tests."""
import unittest
from unittest.mock import patch

from gway_remote.__main__ import deploy_reports, validate, _reports_installed_role

SHA = "a" * 40


class ReportsDeployTests(unittest.TestCase):
    def test_repository_allowlist(self):
        validate("ocpp-reports-deploy", "arthexis/ocpp-reports", SHA)
        with self.assertRaises(ValueError):
            validate("ocpp-reports-deploy", "arthexis/ocpp-csms", SHA)

    def test_pinned_checkout_and_wrapper(self):
        commands = []
        with patch("gway_remote.__main__.subprocess.run",
                   side_effect=lambda cmd, **kwargs: commands.append(cmd)), \
             patch("gway_remote.__main__.subprocess.check_output", return_value=SHA), \
             patch("gway_remote.__main__._reports_installed_role", return_value="terminal"):
            deploy_reports(SHA)
        self.assertEqual(commands[-1], ["bash", "./deploy.sh", "--terminal"])
        self.assertTrue(any(cmd[:3] == ["git", "clone", "--quiet"] for cmd in commands))
        self.assertTrue(any("checkout" in cmd and SHA in cmd for cmd in commands))

    def test_mismatched_checkout_never_deploys(self):
        commands = []
        with patch("gway_remote.__main__.subprocess.run",
                   side_effect=lambda cmd, **kwargs: commands.append(cmd)), \
             patch("gway_remote.__main__.subprocess.check_output", return_value="b" * 40), \
             patch("gway_remote.__main__._reports_installed_role", return_value="control"):
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                deploy_reports(SHA)
        self.assertFalse(any(cmd[:2] == ["bash", "./deploy.sh"] for cmd in commands))

    def test_missing_role_blocks_before_cloning(self):
        with patch("gway_remote.__main__._reports_installed_role",
                   side_effect=RuntimeError("Reports role is not installed")), \
             patch("gway_remote.__main__.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "role is not installed"):
                deploy_reports(SHA)
            run.assert_not_called()

    def test_invalid_role_is_rejected(self):
        with patch("gway_remote.__main__.Path") as path:
            marker = path.return_value
            marker.is_symlink.return_value = False
            marker.is_file.return_value = True
            marker.read_text.return_value = "unknown"
            with self.assertRaisesRegex(RuntimeError, "role preflight invalid"):
                _reports_installed_role()
