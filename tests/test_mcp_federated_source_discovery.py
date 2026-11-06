"""Regression checks for source-level MCP federation."""
import unittest

from gway_remote.mcp_bearer_gateway import inspect_rpc, trusted_source_tool


class FederatedDiscoveryTests(unittest.TestCase):
    def test_namespaced_readonly_source_is_trusted(self):
        tool = {"name": "odoo__customer_search", "annotations": {"readOnlyHint": True}}
        self.assertTrue(trusted_source_tool(tool))

    def test_write_source_is_not_advertised(self):
        self.assertFalse(trusted_source_tool(
            {"name": "odoo__customer_delete", "annotations": {"readOnlyHint": False}}))
        self.assertFalse(trusted_source_tool(
            {"name": "odoo__customer_delete", "annotations": {"readOnlyHint": True, "destructiveHint": True}}))

    def test_unprefixed_and_invalid_names_are_rejected(self):
        for name in ("customer_search", "odoo__bad-name", "node_exec"):
            self.assertFalse(trusted_source_tool(
                {"name": name, "annotations": {"readOnlyHint": True}}))

    def test_namespaced_call_passes_syntax_gate_for_live_validation(self):
        raw = b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"odoo__customer_search","arguments":{}}}'
        self.assertTrue(inspect_rpc(raw))
        self.assertFalse(inspect_rpc(raw.replace(b"odoo__customer_search", b"other-untrusted")))


if __name__ == "__main__":
    unittest.main()
