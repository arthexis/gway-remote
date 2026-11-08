"""Manifest v1 and shared read/execute classification contracts."""
import unittest
from gway_remote.mcp_installed_providers import MANIFEST_FIELDS_V1, MANIFEST_SCHEMA_VERSION
from gway_remote.mcp_tool_scope import required_scope
from gway_remote.mcp_bearer_gateway import inspect_federated_catalog

class FixtureFederation:
    def discover(self, builtins=()):
        tools = list(builtins) + [
            {"name": "fixture__safe", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
            {"name": "fixture__ambiguous", "inputSchema": {"type": "object"}},
            {"name": "fixture__destructive", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True, "destructiveHint": True}},
        ]
        routes = {t["name"]: ("gway-001", "fixture", t["name"], required_scope(t)) for t in tools[len(builtins):]}
        return tools, routes

class ContractTests(unittest.TestCase):
    def test_manifest_v1_unchanged(self):
        self.assertEqual(MANIFEST_SCHEMA_VERSION, 1)
        self.assertEqual(MANIFEST_FIELDS_V1, {"source_id", "revision", "executable", "argv"})

    def test_scope_parity_for_read_ambiguous_and_destructive(self):
        rows = inspect_federated_catalog(FixtureFederation())["tools"]
        scopes = {row["name"]: row["required_scope"] for row in rows}
        self.assertEqual(scopes["fixture__safe"], "gway:read")
        self.assertEqual(scopes["fixture__ambiguous"], "gway:execute")
        self.assertEqual(scopes["fixture__destructive"], "gway:execute")

if __name__ == "__main__":
    unittest.main()
