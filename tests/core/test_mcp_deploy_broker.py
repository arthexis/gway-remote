"""Fixed node_deploy MCP contracts: existing tool name, scoped recipes, safe preview."""
import unittest

from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.mcp_bearer_gateway import (
    ALLOWED_TOOLS, EXEC_TOOL_NAMES, EXEC_TOOLS, NODE_TOOLS,
)


class DeployBrokerTests(unittest.TestCase):
    def setUp(self):
        self.captured = []

        class Stub(AuthorizedExecution):
            def exec(inner, **kwargs):
                self.captured.append(kwargs)
                return {"request_id": kwargs["request_id"], "status": "dispatched"}

            def _allow_preview_eligibility(inner, node):
                self.captured.append({"checked_node": node})

        self.service = Stub(None, None, None)
        self.kwargs = dict(principal="a" * 24, request_id="b" * 32,
                           node="gway-001", application="gway-remote")

    def test_existing_deploy_is_backwards_compatible(self):
        result = self.service.deployment(**self.kwargs)
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(self.captured[-1]["command"],
            "/usr/bin/sudo -n /usr/bin/systemctl start --no-block gway-remote-deploy.service")

    def test_retired_odoo_recipe_is_not_advertised_as_eligible(self):
        with self.assertRaisesRegex(PermissionError, "repository-owned Ansible workflow"):
            self.service.deployment_preview(node="gway-001",
                                            application="odoo-gelectriic")
        with self.assertRaises(PermissionError):
            self.service.deployment(**{**self.kwargs, "application": "odoo-gelectriic"})
        self.assertFalse(any("command" in row for row in self.captured))

    def test_original_status_uses_legacy_receipt(self):
        self.service.deployment(**self.kwargs, status=True)
        self.assertEqual(self.captured[-1]["command"],
            "/usr/bin/cat /var/lib/gway-mcp-deploy/status.json")

    def test_unsupported_nodes_applications_and_revisions_denied(self):
        for changes in ({"node": "gway-002"}, {"node": "gway-004"},
                        {"application": "ocpp-csms"},
                        {"application": "../../other.service"},
                        {"revision": "f" * 40}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, PermissionError)):
                self.service.deployment(**{**self.kwargs, **changes})
        self.assertFalse(any("command" in row for row in self.captured))

    def test_tools_preserve_original_name_and_authentication(self):
        names = {tool["name"] for tool in EXEC_TOOLS}
        self.assertTrue({"node_deploy", "node_deploy_status"} <= names)
        self.assertTrue({"node_deploy", "node_deploy_status"} <= EXEC_TOOL_NAMES)
        self.assertTrue({"node_deploy", "node_deploy_status"} <= ALLOWED_TOOLS)
        self.assertIn("node_deploy_preview", {tool["name"] for tool in NODE_TOOLS})
        self.assertNotIn("deploy", ALLOWED_TOOLS)
        for tool in EXEC_TOOLS:
            if tool["name"].startswith("node_deploy"):
                self.assertEqual(tool["_meta"]["securitySchemes"][0]["scopes"],
                                 ["gway:execute"])
                self.assertEqual(tool["inputSchema"]["properties"]["revision"]["enum"],
                                 ["main"])


if __name__ == "__main__":
    unittest.main()
