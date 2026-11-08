"""Manifest v1 and shared read/execute classification contracts."""
import unittest
from gway_remote.mcp_installed_providers import MANIFEST_FIELDS_V1, MANIFEST_SCHEMA_VERSION
from gway_remote.mcp_tool_scope import required_scope
from gway_remote.mcp_bearer_gateway import inspect_federated_catalog

from tests.helpers.mcp_federation import FederationCatalogFixture, fixture_tool


def federation():
    return FederationCatalogFixture([
        fixture_tool('fixture__safe', read=True),
        fixture_tool('fixture__ambiguous'),
        fixture_tool('fixture__destructive', read=True, destructive=True),
    ])


class ContractTests(unittest.TestCase):
    def test_manifest_v1_unchanged(self):
        self.assertEqual(MANIFEST_SCHEMA_VERSION, 1)
        self.assertEqual(MANIFEST_FIELDS_V1, {"source_id", "revision", "executable", "argv"})

    def test_scope_parity_for_read_ambiguous_and_destructive(self):
        rows = inspect_federated_catalog(federation())["tools"]
        scopes = {row["name"]: row["required_scope"] for row in rows}
        self.assertEqual(scopes["fixture__safe"], "gway:read")
        self.assertEqual(scopes["fixture__ambiguous"], "gway:execute")
        self.assertEqual(scopes["fixture__destructive"], "gway:execute")

if __name__ == "__main__":
    unittest.main()
