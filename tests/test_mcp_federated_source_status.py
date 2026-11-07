"""Regression tests for Watchtower's federated source status."""
import unittest

from gway_remote.mcp_bearer_gateway import federated_source_status


class FakeFederation:
    def __init__(self, routes):
        self.routes = routes

    def discover(self):
        return [], self.routes


class FederatedSourceStatusTests(unittest.TestCase):
    def test_both_node_providers_are_visible(self):
        routes = {
            "agentops__preview": ("gway-001", "agentops", "preview", "read"),
            "agentops__status": ("gway-001", "agentops", "status", "read"),
            "odoo__customer_search": ("gway-001", "odoo", "customer_search", "read"),
        }
        result = federated_source_status(FakeFederation(routes))
        self.assertEqual(result["registered_count"], 2)
        self.assertEqual(result["discovery"], "node_federation")
        self.assertEqual({s["source"] for s in result["sources"]}, {"agentops", "odoo"})
        agent = next(s for s in result["sources"] if s["source"] == "agentops")
        self.assertEqual(agent["tools"], ["agentops__preview", "agentops__status"])

    def test_execute_tools_are_withheld_from_read_diagnostics(self):
        result = federated_source_status(FakeFederation({
            "agentops__preview": ("gway-001", "agentops", "preview", "read"),
            "agentops__submit": ("gway-001", "agentops", "submit", "execute"),
        }))
        self.assertEqual(result["sources"][0]["tools"], ["agentops__preview"])
        self.assertEqual(result["sources"][0]["withheld_execute_count"], 1)

    def test_empty_federation_is_not_legacy_registry(self):
        self.assertEqual(federated_source_status(FakeFederation({})),
                         {"sources": [], "registered_count": 0,
                          "discovery": "node_federation"})


if __name__ == "__main__":
    unittest.main()
