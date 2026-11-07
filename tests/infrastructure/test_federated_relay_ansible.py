"""Ensure Ansible's existing SSH relay supplies the node-owned provider policy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELAY = ROOT / "ansible/roles/gway_remote/tasks/node-exec-relay.yml"
MAIN = ROOT / "ansible/roles/gway_remote/tasks/main.yml"


def test_relay_passes_node_policy_through_forced_command_and_sudoers():
    data = RELAY.read_text()
    command = ("PYTHONPATH={{ gway_remote_install_root }} "
               "GWAY_MCP_SOURCE_POLICY=/etc/gway-mcp-gateway/sources.json "
               "/usr/bin/python3 -m gway_remote.node_exec_protocol")
    assert data.count(command) == 2
    assert "ForceCommand /usr/bin/sudo -n -u" in data
    assert "NOPASSWD: /usr/bin/env " in data
    assert "gway_exec_relay_public_key is defined" in data


def test_relay_opt_in_supports_enrolled_nodes():
    assert "is match('^gway-[0-9]+$')" in MAIN.read_text()
    assert "gway_exec_transport_prepare | default(false) | bool" in MAIN.read_text()


def test_receiver_rejects_spoofed_node_identity():
    import json
    from unittest.mock import patch
    from gway_remote.node_exec_protocol import serve_one
    payload = {"operation": "provider_list", "node": "gway-002",
               "request_id": "a" * 32}
    with patch("gway_remote.node_exec_protocol.require_account"):
        try:
            serve_one(json.dumps(payload).encode(), hostname="gway-001")
        except PermissionError:
            pass
        else:
            raise AssertionError("spoofed node was accepted")
