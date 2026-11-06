import unittest
from gway_remote.mcp_bridge_authorization import BridgeAuthorization


class Verifier:
    def __init__(self):
        self.valid = True
        self.scope_calls = []

    def verify(self, credential, *, required_scope):
        self.scope_calls.append(required_scope)
        return self.valid and credential == "trusted-token"

    def execution_principal(self, credential):
        return "operator-root"


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.verifier = Verifier()
        self.tokens = {"operator-root": "trusted-token"}
        self.authorize = BridgeAuthorization(
            verifier=self.verifier,
            credential_for_principal=lambda principal: self.tokens.get(principal),
            allowed_node=lambda principal, node: node == "gway-001")

    def test_read_requires_live_credential_and_node(self):
        self.assertTrue(self.authorize("operator-root", "gway-001", "gway:read"))
        self.assertFalse(self.authorize("operator-root", "gway-002", "gway:read"))
        self.verifier.valid = False
        self.assertFalse(self.authorize("operator-root", "gway-001", "gway:read"))

    def test_execute_binds_parent_principal(self):
        self.assertTrue(self.authorize("operator-root", "gway-001", "gway:execute"))
        self.tokens["other"] = "trusted-token"
        self.assertFalse(self.authorize("other", "gway-001", "gway:execute"))
        self.assertIn("gway:execute", self.verifier.scope_calls)

    def test_unknown_principal_denied(self):
        self.assertFalse(self.authorize("unknown", "gway-001", "gway:read"))


if __name__ == "__main__":
    unittest.main()
