"""Offline integration of Fleet collection through the real node JSON protocol.

Only the SSH process is simulated; the read operation and MCP tool dispatcher
are exercised without installing a provider or invoking arbitrary commands.
"""
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from gway_remote.fleet_contract import collect_authenticated
from gway_remote.mcp_provider_transport import ProviderTransport
from gway_remote.node_exec_protocol import serve_one
from gway_remote.fleet_diagnostics_provider import dispatch, TOOLS


NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


class OfflineSSH:
    def __init__(self):
        from types import SimpleNamespace
        self.node = SimpleNamespace(node="gway-001")
        self.requests = []

    def invoke(self, payload):
        self.requests.append(payload)
        from gway_remote.node_exec_protocol import serve_one
        from gway_remote.mcp_node_providers import dispatch_node_provider_request
        from gway_remote.mcp_installed_providers import discover_installed_providers
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.node_exec_protocol.socket.gethostname", return_value="gway-001"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers", return_value=()), \
             patch("gway_remote.mcp_node_providers.dispatch_node_provider_request", side_effect=self.provider_dispatch):
            return serve_one(json.dumps(payload).encode("utf-8"))

    def provider_dispatch(self, registrations, request, *, node_id, trusted_scope):
        if request["operation"] == "provider_list":
            return {"node": node_id, "providers": [{"node": node_id, "provider": "diagnostics",
                "revision": "test", "status": "available", "tools": list(TOOLS)}]}
        if trusted_scope != "read" or request["provider"] != "diagnostics":
            raise PermissionError("unauthorized")
        if request["tool"] == "hardware":
            with patch("gway_remote.fleet_diagnostics_provider.inspect", return_value={
                "schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(),
                "host": {"cpu_temperature_c": 42}}):
                return dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "hardware", "arguments": {}}})["result"]
        raise TimeoutError("status unavailable")


class IntegrationTests(unittest.TestCase):
    def test_attested_node_read_only_partial_and_scope_injection(self):
        ssh = OfflineSSH()
        federation = type("Federation", (), {"transport": ProviderTransport(ssh)})()
        inventory = {"source": "watchtower-enrollment-ledger", "generated_at": NOW.isoformat(),
                     "nodes": [{"node": "gway-001", "identity_verified": True}]}
        row = collect_authenticated(inventory, federation, now=NOW)["nodes"][0]
        self.assertTrue(row["hardware"]["available"])
        self.assertEqual(row["hardware"]["data"]["cpu_temperature_c"], 42)
        self.assertFalse(row["services"]["available"])
        self.assertEqual([p["operation"] for p in ssh.requests],
                         ["provider_list", "provider_read_call", "provider_read_call"])
        self.assertTrue(all("authorized_scope" not in p for p in ssh.requests))
        injected = dict(ssh.requests[1], authorized_scope="execute")
        with self.assertRaises(ValueError), patch("gway_remote.node_exec_protocol.require_account"):
            serve_one(json.dumps(injected).encode(), hostname="gway-001")

    def test_unattested_node_never_contacts_transport(self):
        ssh = OfflineSSH()
        federation = type("Federation", (), {"transport": ProviderTransport(ssh)})()
        inventory = {"source": "watchtower-enrollment-ledger", "generated_at": NOW.isoformat(),
                     "nodes": [{"node": "gway-001", "identity_verified": False}]}
        row = collect_authenticated(inventory, federation, now=NOW)["nodes"][0]
        self.assertFalse(row["hardware"]["available"])
        self.assertEqual(ssh.requests, [])

    def test_untrusted_inventory_fails_before_transport(self):
        ssh = OfflineSSH()
        federation = type("Federation", (), {"transport": ProviderTransport(ssh)})()
        base = {"source": "watchtower-enrollment-ledger", "generated_at": NOW.isoformat(),
                "nodes": [{"node": "gway-001", "identity_verified": True}]}
        cases = [
            {**base, "source": "untrusted"},
            {**base, "generated_at": (NOW - timedelta(minutes=3)).isoformat()},
            {**base, "nodes": base["nodes"] * 2},
            {**base, "nodes": [{"node": "gway-999;id", "identity_verified": True}]},
        ]
        for inventory in cases:
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                collect_authenticated(inventory, federation, now=NOW)
        self.assertEqual(ssh.requests, [])

    def test_malformed_provider_catalog_never_dispatches_call(self):
        class Transport:
            def __init__(self):
                self.calls = []
            def invoke(self, node, request, *, trusted_scope):
                self.calls.append(request)
                return {"node": node, "providers": [{"node": node, "provider": "diagnostics",
                    "revision": "test", "status": "available", "tools": [
                        {"name": "hardware", "annotations": {"readOnlyHint": True}},
                        {"name": "hardware", "annotations": {"readOnlyHint": True}}]}]}
        transport = Transport()
        federation = type("Federation", (), {"transport": transport})()
        inventory = {"source": "watchtower-enrollment-ledger", "generated_at": NOW.isoformat(),
                     "nodes": [{"node": "gway-001", "identity_verified": True}]}
        row = collect_authenticated(inventory, federation, now=NOW)["nodes"][0]
        self.assertFalse(row["hardware"]["available"])
        self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
