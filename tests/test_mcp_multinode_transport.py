"""Regression tests for trusted per-node transport selection."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote.watchtower_exec_transport import MultiNodeTransport
from gway_remote.watchtower_exec_auth import AuthorizedExecution


class MultiNodeTransportTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def transport(node):
            def invoke(payload):
                self.calls.append((node, payload["operation"]))
                return {"node": node, "request_id": payload["request_id"]}
            return SimpleNamespace(node=SimpleNamespace(node=node,
                wireguard_address="10.90.0.2" if node == "gway-001" else "10.90.0.3",
                host_key_sha256="a" * 64 if node == "gway-001" else "b" * 64), invoke=invoke)
        self.router = MultiNodeTransport({"gway-001": transport("gway-001"),
                                          "gway-002": transport("gway-002")})

    def test_routes_to_selected_node(self):
        for node in ("gway-001", "gway-002"):
            result = self.router.invoke({"node": node, "operation": "limits", "request_id": "f" * 32})
            self.assertEqual(result["node"], node)
        self.assertEqual(self.calls, [("gway-001", "limits"), ("gway-002", "limits")])

    def test_unknown_node_fails_closed(self):
        with self.assertRaises(PermissionError):
            self.router.for_node("gway-999")

    def test_eligibility_matches_pinned_address(self):
        auth = AuthorizedExecution(None, None, SimpleNamespace(transport=self.router), enabled=True)
        nodes = [{"node": name, "registered": True, "identity_verified": True,
                  "execute_eligible": True, "reachable": "reachable",
                  "address": self.router.for_node(name).node.wireguard_address}
                 for name in ("gway-001", "gway-002")]
        with patch("gway_remote.node_registry_inventory.load", return_value={"nodes": nodes}):
            auth._current_eligibility("gway-002")
            nodes[1]["address"] = "10.90.0.99"
            with self.assertRaises(PermissionError):
                auth._current_eligibility("gway-002")
            nodes[1]["address"] = "10.90.0.3"
            nodes[1]["execute_eligible"] = False
            with self.assertRaises(PermissionError):
                auth._current_eligibility("gway-002")


if __name__ == "__main__":
    unittest.main()
