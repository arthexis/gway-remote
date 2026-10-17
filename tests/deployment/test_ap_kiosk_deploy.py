"""Behavioral tests for the AP kiosk deployment adapter."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.__main__ import deploy_ap_kiosk, validate

SHA = "a" * 40


class ApKioskDeployTests(unittest.TestCase):
    def test_repository_is_allowlisted(self):
        validate("ap-kiosk-deploy", "arthexis/gway-ap-kiosk", SHA)
        with self.assertRaises(ValueError):
            validate("ap-kiosk-deploy", "arthexis/ocpp-csms", SHA)

    def test_uses_pinned_checkout_and_canonical_wrapper(self):
        commands = []
        def run(cmd, **kwargs):
            commands.append((cmd, kwargs))
        with patch("gway_remote.__main__.subprocess.run", side_effect=run), \
             patch("gway_remote.__main__.subprocess.check_output", return_value=SHA):
            deploy_ap_kiosk(SHA)
        self.assertEqual(["bash", "./deploy.sh"], commands[-1][0])
        self.assertTrue(any(cmd[:3] == ["git", "clone", "--quiet"] for cmd, _ in commands))
        self.assertTrue(any("checkout" in cmd and SHA in cmd for cmd, _ in commands))

    def test_mismatched_checkout_never_runs_ansible(self):
        commands = []
        with patch("gway_remote.__main__.subprocess.run", side_effect=lambda cmd, **kw: commands.append(cmd)), \
             patch("gway_remote.__main__.subprocess.check_output", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                deploy_ap_kiosk(SHA)
        self.assertFalse(any(cmd[:2] == ["bash", "./deploy.sh"] for cmd in commands))
