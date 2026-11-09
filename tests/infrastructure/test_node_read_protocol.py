"""Offline policy regression for dormant read-only SSH forced-command entrypoint."""
import json
import unittest
from unittest.mock import patch

from gway_remote.node_exec_protocol import READ_ONLY_OPERATIONS, serve_one

RID = "0123456789abcdef0123456789abcdef"


class ReadRelayTests(unittest.TestCase):
    def request(self, operation, **kwargs):
        return json.dumps({"operation": operation, "node": "gway-001",
                           "request_id": RID, **kwargs}).encode()

    def test_read_identity_allows_discovery_and_enforces_read_scope(self):
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                   return_value=[]), \
             patch("gway_remote.mcp_node_providers.dispatch_node_provider_request",
                   return_value={"ok": True}) as dispatch:
            response = serve_one(self.request("provider_read_call",
                provider="diagnostics", tool="hardware", arguments={}),
                hostname="gway-001", allowed_operations=READ_ONLY_OPERATIONS)
            self.assertEqual(response["result"], {"ok": True})
            self.assertEqual(dispatch.call_args.kwargs["trusted_scope"], "read")

    def test_read_identity_denies_legacy_execute_and_arbitrary_jobs(self):
        cases = [
            ("provider_call", {"provider": "odoo", "tool": "write",
                               "arguments": {}, "authorized_scope": "execute"}),
            ("submit", {"command": "id"}),
            ("cancel", {}),
            ("result", {"cursor": 0}),
            ("limits", {}),
        ]
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers") as discover:
            for operation, args in cases:
                with self.subTest(operation=operation), self.assertRaises(PermissionError):
                    serve_one(self.request(operation, **args), hostname="gway-001",
                              allowed_operations=READ_ONLY_OPERATIONS)
            discover.assert_not_called()

    def test_identity_mismatch_and_scope_injection_fail(self):
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                   return_value=[]):
            request = self.request("provider_read_call", provider="diagnostics",
                                   tool="hardware", arguments={})
            with self.assertRaises(PermissionError):
                serve_one(request, hostname="gway-002",
                          allowed_operations=READ_ONLY_OPERATIONS)
            with self.assertRaises(ValueError):
                serve_one(self.request("provider_read_call", provider="diagnostics",
                    tool="hardware", arguments={}, authorized_scope="execute"),
                    hostname="gway-001", allowed_operations=READ_ONLY_OPERATIONS)

    def test_policy_is_not_request_controlled(self):
        with patch("gway_remote.node_exec_protocol.require_account"):
            with self.assertRaises(ValueError):
                serve_one(self.request("provider_list"), hostname="gway-001",
                          allowed_operations={"provider_list"})
            with self.assertRaises(ValueError):
                serve_one(self.request("provider_list"), hostname="gway-001",
                          allowed_operations=frozenset({"submit", "arbitrary"}))


if __name__ == "__main__":
    unittest.main()
