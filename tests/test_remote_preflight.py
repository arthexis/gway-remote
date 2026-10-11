"""Architectural guardrails for the read-only remote access preflight."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RemotePreflightTests(unittest.TestCase):
    def test_preflight_is_read_only(self):
        script = (ROOT / "scripts/remote-preflight.sh").read_text()
        self.assertIn("set -eu", script)
        self.assertIn("remote.arthexis.com", script)
        self.assertIn("wg show interfaces", script)
        self.assertNotIn("wg show all", script)
        for forbidden in ("sudo ", "systemctl enable", "systemctl restart",
                          "systemctl stop", "ufw allow", "ufw delete",
                          "iptables -", "nft add", "wg set ", "sed -i",
                          "certbot ", "tee /etc/", "cat /etc/wireguard"):
            self.assertNotIn(forbidden, script)

    def test_plan_requires_discovery_before_changes(self):
        doc = (ROOT / "docs/remote-phase-a.md").read_text()
        for requirement in ("lightsail", "rollback", "subnet collision",
                            "certificate", "unknown"):
            self.assertIn(requirement, doc.lower())
