"""Node-owned deployment preview and fail-closed execution contracts."""
import unittest
from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.mcp_bearer_gateway import ALLOWED_TOOLS, EXEC_TOOL_NAMES, EXEC_TOOLS, NODE_TOOLS


class Pinned:
    class Node:
        node = "gway-001"
    node = Node()

    def invoke(self, payload):
        return {"node": payload["node"], "request_id": payload["request_id"],
                "result": {"application": payload["application"], "status": "declared"}}


class BrokerTests(unittest.TestCase):
    def setUp(self):
        class Service(AuthorizedExecution):
            def _allow_preview_eligibility(self, node):
                if node != "gway-001":
                    raise PermissionError("node denied")
        self.service = Service(None, None, type("Relay", (), {"transport": Pinned()})())

    def test_remote_preview(self):
        from unittest.mock import patch
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=Pinned()):
            result = self.service.deployment_preview(node="gway-001", application="agentops")
            self.assertEqual(result["status"], "eligible")
            with self.assertRaises(PermissionError):
                self.service.deployment(principal="a"*24, request_id="b"*32,
                                        node="gway-001", application="agentops")

    def test_status_requires_existing_request_binding(self):
        from unittest.mock import patch
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=Pinned()):
            with patch.object(self.service, "_allow", return_value=None):
                with patch.object(self.service, "_current_eligibility", return_value=None):
                    with self.assertRaises((AttributeError, ValueError)):
                        self.service.deployment(principal="a"*24, request_id="b"*32,
                            node="gway-001", application="agentops", status=True)
                    with self.assertRaises(PermissionError):
                        self.service.deployment(principal="a"*24, request_id="b"*32,
                            node="gway-001", application="agentops")

    def test_negative_targets(self):
        for app in ("../bad", "agentops;id", ""):
            with self.assertRaises(ValueError):
                self.service.deployment_preview(node="gway-001", application=app)
        with self.assertRaises(PermissionError):
            self.service.deployment_preview(node="gway-002", application="agentops")

    def test_scopes_preserved(self):
        self.assertTrue({"node_deploy", "node_deploy_status"} <= EXEC_TOOL_NAMES)
        self.assertTrue({"node_deploy", "node_deploy_status"} <= ALLOWED_TOOLS)
        self.assertIn("node_deploy_preview", {t["name"] for t in NODE_TOOLS})
        for tool in EXEC_TOOLS:
            if tool["name"].startswith("node_deploy"):
                self.assertEqual(tool["_meta"]["securitySchemes"][0]["scopes"], ["gway:execute"])


if __name__ == "__main__":
    unittest.main()
