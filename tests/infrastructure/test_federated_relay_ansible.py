"""Regression coverage for node-owned MCP relay provisioning."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.node_exec_protocol import serve_one

ROOT = Path(__file__).resolve().parents[2]
RELAY = ROOT / "ansible/roles/gway_remote/tasks/node-exec-relay.yml"
MAIN = ROOT / "ansible/roles/gway_remote/tasks/main.yml"


class FederatedRelayAnsibleTests(unittest.TestCase):
    def test_relay_passes_node_policy_through_forced_command_and_sudoers(self):
        data = RELAY.read_text()
        command = ("PYTHONPATH={{ gway_remote_install_root }} "
                   "GWAY_MCP_SOURCE_POLICY=/etc/gway-mcp-gateway/sources.json "
                   "/usr/bin/python3 -m gway_remote.node_exec_protocol")
        self.assertEqual(data.count(command), 2)
        self.assertIn("ForceCommand /usr/bin/sudo -n -u", data)
        self.assertIn("NOPASSWD: /usr/bin/env ", data)
        self.assertIn("gway_exec_relay_public_key is defined", data)

    def test_relay_opt_in_supports_enrolled_nodes(self):
        self.assertIn("is match('^gway-[0-9]+$')", MAIN.read_text())
        self.assertIn("gway_exec_transport_prepare | default(false) | bool", MAIN.read_text())

    def test_receiver_rejects_spoofed_node_identity(self):
        payload = {"operation": "provider_list", "node": "gway-002",
                   "request_id": "a" * 32}
        with patch("gway_remote.node_exec_protocol.require_account"):
            with self.assertRaises(PermissionError):
                serve_one(json.dumps(payload).encode(), hostname="gway-001")


if __name__ == "__main__":
    unittest.main()
