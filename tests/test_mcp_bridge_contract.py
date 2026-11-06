import unittest

from gway_remote.mcp_bridge_contract import InvalidBridgeRequest, validate_envelope


class BridgeContractTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "version": 1, "request_id": "a" * 32, "principal": "operator-1",
            "audience": "gway-001", "operation": "inventory.list",
            "scope": "gway:read", "issued_at": 100, "expires_at": 130,
            "arguments": {},
        }

    def test_valid_read(self):
        self.assertEqual(validate_envelope(self.request, audience="gway-001", now=101), self.request)

    def test_execute_requires_scope(self):
        self.request["operation"] = "execution.start"
        with self.assertRaises(InvalidBridgeRequest):
            validate_envelope(self.request, audience="gway-001", now=101)
        self.request["scope"] = "gway:execute"
        validate_envelope(self.request, audience="gway-001", now=101)

    def test_wrong_audience(self):
        with self.assertRaises(InvalidBridgeRequest):
            validate_envelope(self.request, audience="gway-002", now=101)

    def test_expired(self):
        with self.assertRaises(InvalidBridgeRequest):
            validate_envelope(self.request, audience="gway-001", now=130)

    def test_extra_fields_rejected(self):
        self.request["address"] = "127.0.0.1"
        with self.assertRaises(InvalidBridgeRequest):
            validate_envelope(self.request, audience="gway-001", now=101)


if __name__ == "__main__":
    unittest.main()
