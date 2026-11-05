"""MCP preview reports bounded observed executor concurrency, not a static claim."""
import json
import unittest
from unittest.mock import patch
from gway_remote.mcp_bearer_gateway import local_node_result
from gway_remote.node_exec_protocol import serve_one

INVENTORY = {"nodes": [{"node": "gway-001", "registered": True,
                         "identity_verified": True, "execute_available": True}]}

class FakeTransport:
    def __init__(self, value=3, error=None):
        self.node = type("Pinned", (), {"node": "gway-001"})()
        self.value = value
        self.error = error
        self.calls = []
    def invoke(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return {"node": request["node"], "request_id": request["request_id"],
                "concurrent_jobs_per_node": self.value}

class EffectiveConcurrencyTests(unittest.TestCase):
    def preview(self, transport):
        execution = type("Execution", (), {"relay": type("Relay", (), {
            "transport": transport})()})()
        with patch("gway_remote.node_registry_inventory.public_nodes",
                   return_value=INVENTORY):
            return local_node_result("node_exec_preview",
                                     {"node": "gway-001", "command": "uptime"},
                                     execution=execution)

    def test_observed_limit(self):
        transport = FakeTransport(3)
        result = self.preview(transport)
        self.assertEqual(result["limits"]["concurrent_jobs_per_node"], 3)
        self.assertEqual(result["execution_health"], "unverified")
        self.assertEqual(transport.calls[0]["operation"], "limits")
        self.assertRegex(transport.calls[0]["request_id"], r"^[0-9a-f]{32}$")

    def test_missing_or_invalid_response_does_not_claim_one(self):
        for transport in (FakeTransport(error=OSError("offline")),
                          FakeTransport(error=ValueError("bad data")),
                          FakeTransport(99)):
            with self.subTest(transport=transport):
                self.assertIsNone(self.preview(transport)["limits"]["concurrent_jobs_per_node"])

    def test_node_protocol_limits_is_read_only(self):
        raw = json.dumps({"operation": "limits", "node": "gway-001",
                          "request_id": "a"*32}).encode()
        with patch("gway_remote.node_exec_protocol.require_account"), patch(
            "gway_remote.node_exec_protocol.configured_max_active", return_value=3):
            result = serve_one(raw, hostname="gway-001")
        self.assertEqual(result["concurrent_jobs_per_node"], 3)
        self.assertEqual(result["request_id"], "a"*32)

if __name__ == "__main__":
    unittest.main()
