"""Regression coverage for node-owned MCP relay provisioning."""
import json
import os
import shutil
import subprocess
import tempfile
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

    @unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible unavailable")
    def test_relay_preflight_accepts_managed_nodes_and_rejects_invalid_inputs(self):
        # Run the actual first task in isolation; no account or SSH changes.
        parts = RELAY.read_text().split("\n# Install SSH's enforced restrictions", 1)
        self.assertEqual(len(parts), 2, "relay preflight boundary changed")
        first_task = parts[0]
        self.assertEqual(first_task.count("\n- name:"), 1)
        with tempfile.TemporaryDirectory() as temp:
            playbook = Path(temp) / "preflight.yml"
            tasks = Path(temp) / "tasks.yml"
            tasks.write_text(first_task + "\n")
            playbook.write_text(
                "- hosts: localhost\n  connection: local\n  gather_facts: false\n"
                "  tasks:\n    - import_tasks: tasks.yml\n"
            )
            key = "ssh-ed25519 " + "A" * 44
            for host, public_key, expected in (
                ("gway-001", key, 0), ("gway-004", key, 0),
                ("watchtower", key, 1), ("gway-004-extra", key, 1),
                ("gway-004", "invalid", 1), ("gway-004", None, 1),
            ):
                with self.subTest(host=host, public_key=public_key):
                    variables = {"ansible_hostname": host}
                    if public_key is not None:
                        variables["gway_exec_relay_public_key"] = public_key
                    result = subprocess.run(
                        ["ansible-playbook", "-i", "localhost,", str(playbook),
                         "-e", json.dumps(variables)], capture_output=True, text=True,
                        env={**os.environ, "ANSIBLE_LOCAL_TEMP": temp}, timeout=30)
                    self.assertEqual(result.returncode == 0, expected == 0, result.stdout + result.stderr)

    def test_receiver_rejects_spoofed_node_identity(self):
        payload = {"operation": "provider_list", "node": "gway-002",
                   "request_id": "a" * 32}
        with patch("gway_remote.node_exec_protocol.require_account"):
            with self.assertRaises(PermissionError):
                serve_one(json.dumps(payload).encode(), hostname="gway-001")


if __name__ == "__main__":
    unittest.main()
