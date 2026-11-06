import unittest
from gway_remote.mcp_bridge_dispatch import WatchtowerBridgeDispatch
from gway_remote.mcp_bridge_contract import InvalidBridgeRequest


class InventoryStub:
    def __init__(self):
        self.calls = []

    def public_nodes(self, *, execution_enabled):
        self.calls.append(("list", execution_enabled))
        return {"nodes": []}

    def capabilities(self, node, *, execution_enabled):
        self.calls.append(("capabilities", node, execution_enabled))
        return {"node": node}


class WatchtowerBridgeDispatchTests(unittest.TestCase):
    def setUp(self):
        self.inventory = InventoryStub()
        self.envelope = {"principal": "operator", "audience": "gway-001",
                         "scope": "gway:read", "operation": "inventory.list",
                         "arguments": {}}

    def test_authorized_inventory(self):
        dispatch = WatchtowerBridgeDispatch(
            authorize=lambda principal, audience, scope: (
                principal, audience, scope) == ("operator", "gway-001", "gway:read"),
            inventory=self.inventory)
        self.assertEqual(dispatch(self.envelope), {"nodes": []})
        self.assertEqual(self.inventory.calls, [("list", False)])

    def test_denied_principal_never_reaches_inventory(self):
        dispatch = WatchtowerBridgeDispatch(authorize=lambda *args: False,
                                             inventory=self.inventory)
        with self.assertRaises(PermissionError):
            dispatch(self.envelope)
        self.assertEqual(self.inventory.calls, [])

    def test_execution_is_not_implicitly_enabled(self):
        dispatch = WatchtowerBridgeDispatch(authorize=lambda *args: True,
                                             inventory=self.inventory)
        self.envelope["scope"] = "gway:execute"
        self.envelope["operation"] = "execution.start"
        with self.assertRaises(InvalidBridgeRequest):
            dispatch(self.envelope)
        self.assertEqual(self.inventory.calls, [])

    def test_capabilities(self):
        dispatch = WatchtowerBridgeDispatch(authorize=lambda *args: True,
                                             inventory=self.inventory)
        self.envelope["operation"] = "inventory.capabilities"
        self.envelope["arguments"] = {"node": "gway-002"}
        self.assertEqual(dispatch(self.envelope), {"node": "gway-002"})


if __name__ == "__main__":
    unittest.main()
