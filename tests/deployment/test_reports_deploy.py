"""Reports appliance deployment adapter regression tests."""
import unittest
from unittest.mock import patch

from gway_remote.__main__ import deploy_reports, validate

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
             patch("gway_remote.__main__.subprocess.check_output", return_value=SHA):
            deploy_reports(SHA)
        self.assertEqual(commands[-1], ["bash", "./deploy.sh"])
        self.assertTrue(any(cmd[:3] == ["git", "clone", "--quiet"] for cmd in commands))
        self.assertTrue(any("checkout" in cmd and SHA in cmd for cmd in commands))

    def test_mismatched_checkout_never_deploys(self):
        commands = []
        with patch("gway_remote.__main__.subprocess.run",
                   side_effect=lambda cmd, **kwargs: commands.append(cmd)), \
             patch("gway_remote.__main__.subprocess.check_output", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                deploy_reports(SHA)
        self.assertFalse(any(cmd[:2] == ["bash", "./deploy.sh"] for cmd in commands))
