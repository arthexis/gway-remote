import unittest

from gway_remote.mcp_bridge_session import SessionBridgeDispatch
from gway_remote.mcp_bridge_contract import InvalidBridgeRequest


class Verifier:
    valid = True
    def verify(self, token, *, required_scope):
        return self.valid and token == "trusted" and required_scope in ("gway:read", "gway:execute")
    def execution_principal(self, token):
        return "a" * 24


class Execution:
    def __init__(self):
        self.calls = []
    def exec(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "dispatched"}
    def result(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "running"}
    def cancel(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "cancelled"}
    def deployment(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "dispatched"}


class Inventory:
    def public_nodes(self, *, execution_enabled):
        return {"nodes": [], "execution_enabled": execution_enabled}


class SessionDispatchTests(unittest.TestCase):
    def setUp(self):
        self.verifier = Verifier()
        self.execution = Execution()
        self.dispatch = SessionBridgeDispatch(
            verifier=self.verifier, session_token="trusted",
            allowed_node=lambda token, node: node == "gway-001",
            read_principal=lambda token: "reader",
            execution=self.execution, inventory=Inventory())
        self.request = {"principal": "a" * 24, "audience": "gway-001",
                        "scope": "gway:execute", "operation": "execution.start",
                        "arguments": {"node": "gway-001", "command": "true", "request_id": "b" * 32}}

    def test_execute_uses_verified_parent(self):
        self.assertEqual(self.dispatch(self.request), {"status": "dispatched"})
        self.assertEqual(self.execution.calls[0]["principal"], "a" * 24)

    def test_spoofed_principal_denied(self):
        self.request["principal"] = "attacker"
        with self.assertRaises(PermissionError):
            self.dispatch(self.request)
        self.assertFalse(self.execution.calls)

    def test_revoked_session_denied(self):
        self.verifier.valid = False
        with self.assertRaises(PermissionError):
            self.dispatch(self.request)
        self.assertFalse(self.execution.calls)

    def test_read_identity_binding(self):
        self.request.update(principal="reader", scope="gway:read",
                            operation="inventory.list", arguments={})
        self.assertEqual(self.dispatch(self.request)["nodes"], [])
        self.request["principal"] = "attacker"
        with self.assertRaises(PermissionError):
            self.dispatch(self.request)

    def test_cross_node_execution_arguments_denied(self):
        self.request["arguments"]["node"] = "gway-002"
        with self.assertRaises(PermissionError):
            self.dispatch(self.request)
        self.assertFalse(self.execution.calls)

    def test_cross_node_capabilities_denied(self):
        self.request.update(principal="reader", scope="gway:read",
                            operation="inventory.capabilities",
                            arguments={"node": "gway-002"})
        with self.assertRaises(PermissionError):
            self.dispatch(self.request)

    def test_result_and_cancel_keep_principal(self):
        self.request.update(operation="execution.result", arguments={"request_id": "b" * 32})
        self.dispatch(self.request)
        self.request["operation"] = "execution.cancel"
        self.dispatch(self.request)
        self.assertTrue(all(x["principal"] == "a" * 24 for x in self.execution.calls))


if __name__ == "__main__":
    unittest.main()
