"""Fail-closed effective SSH profile checks."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from gway_remote.inspection_ssh_trust import validate_profile


class SSHTrustTests(unittest.TestCase):
    def profile(self, extra=""):
        return ("hostname 10.90.0.4\nuser arthe\nbatchmode yes\n"
                "stricthostkeychecking yes\nidentitiesonly yes\n"
                "proxyjump gelectriic.com\n"
                "userknownhostsfile /etc/ssh/known_hosts\n"
                "identityfile /etc/ssh/inspection-key\n" + extra)

    def check(self, effective):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, effective, ""))
        with patch("gway_remote.inspection_ssh_trust.trusted_file"):
            return validate_profile("/etc/ssh/config", "gway-004",
                                    hostname="10.90.0.4", require_jump=True, runner=runner)

    def test_valid_profile(self):
        self.assertEqual(self.check(self.profile())["user"], "arthe")

    def test_reject_missing_bastion(self):
        with self.assertRaises(ValueError):
            self.check(self.profile("proxyjump none\n"))

    def test_reject_unpinned_host(self):
        with self.assertRaises(ValueError):
            self.check(self.profile("stricthostkeychecking no\n"))

    def test_reject_agent_identity_fallback(self):
        with self.assertRaises(ValueError):
            self.check(self.profile("identitiesonly no\n"))

    def test_reject_root(self):
        with self.assertRaises(ValueError):
            self.check(self.profile("user root\n"))

    def test_reject_wrong_destination(self):
        with self.assertRaises(ValueError):
            self.check(self.profile("hostname 10.90.0.5\n"))
