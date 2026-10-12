from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WireguardAdoptionTests(unittest.TestCase):
    def test_existing_tunnel_only(self):
        playbook = (ROOT / "ansible/playbooks/adopt-wireguard-peer.yml").read_text()
        self.assertIn("hosts: wireguard_hub", playbook)
        self.assertIn("backup: true", playbook)
        self.assertIn("wg_peer_config.changed", playbook)
        self.assertIn("allowed-ips", playbook)
        for forbidden in ("wg-quick up", "wg-quick down", "systemctl restart",
                          "PrivateKey =", "10.77.0.", "iptables -A", "ufw allow"):
            self.assertNotIn(forbidden, playbook)
