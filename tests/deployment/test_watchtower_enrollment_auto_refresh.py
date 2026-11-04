"""Watchtower enrollment deployment stays separate from satellite/bootstrap flows."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TestWatchtowerEnrollmentAutoRefresh(unittest.TestCase):
    def test_auto_deploy_refreshes_only_existing_watchtower_enrollment(self):
        script = (ROOT / "scripts/watchtower-auto-deploy.sh").read_text()
        self.assertTrue("watchtower-enrollment-refresh.yml" in script)
        self.assertTrue(script.index("watchtower-mcp.yml") < script.index("watchtower-enrollment-refresh.yml"))
        play = (ROOT / "ansible/playbooks/watchtower-enrollment-refresh.yml").read_text()
        self.assertTrue("hosts: localhost" in play)
        self.assertTrue("Refuse to provision a new enrollment owner" in play)
        self.assertTrue("Require already-enabled enrollment service" in play)
        self.assertTrue("127.0.0.1" in play)
        self.assertTrue("when: enrollment_code.changed" in play)
        self.assertTrue("register(" not in play)
        self.assertTrue("bootstrap_sessions" not in play)
        self.assertTrue("watchtower-enrollment-production.yml" not in script)
