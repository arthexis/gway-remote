"""Fixed deployment command never accepts an MCP shell, service, or git ref."""
import unittest
from unittest.mock import patch
from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.mcp_bearer_gateway import ALLOWED_TOOLS, EXEC_TOOL_NAMES, EXEC_TOOLS

class DeployBrokerTests(unittest.TestCase):
    def setUp(self):
        self.captured = []
        class Stub(AuthorizedExecution):
            def exec(inner, **kwargs):
                self.captured.append(kwargs)
                return {"request_id": kwargs["request_id"], "status": "dispatched"}
        self.service = Stub(None, None, None)
        self.kwargs = dict(principal="a"*24, request_id="b"*32,
                           node="gway-001", application="gway-remote")

    def test_start_is_one_fixed_unit_only(self):
        result = self.service.deployment(**self.kwargs)
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(self.captured[0]["command"],
            "/usr/bin/sudo -n /usr/bin/systemctl start --no-block gway-remote-deploy.service")

    def test_status_is_unprivileged_and_fixed(self):
        self.service.deployment(**self.kwargs, status=True)
        self.assertEqual(self.captured[0]["command"],
            "/usr/bin/systemctl show gway-remote-deploy.service "
            "--property=ActiveState,SubState,Result,ExecMainStatus --no-pager")

    def test_other_nodes_and_applications_denied(self):
        for changes in ({"node": "gway-002"}, {"application": "ocpp-csms"},
                        {"application": "../../other.service"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.service.deployment(**{**self.kwargs, **changes})
        self.assertEqual(self.captured, [])

    def test_tools_require_execute_scope_and_are_advertised(self):
        names = {tool["name"] for tool in EXEC_TOOLS}
        self.assertTrue({"node_deploy", "node_deploy_status"} <= names)
        self.assertTrue({"node_deploy", "node_deploy_status"} <= EXEC_TOOL_NAMES)
        self.assertTrue({"node_deploy", "node_deploy_status"} <= ALLOWED_TOOLS)
        for tool in EXEC_TOOLS:
            if tool["name"].startswith("node_deploy"):
                self.assertEqual(tool["_meta"]["securitySchemes"][0]["scopes"],
                                 ["gway:execute"])
                self.assertEqual(tool["inputSchema"]["properties"]["application"]["enum"],
                                 ["gway-remote"])

if __name__ == "__main__":
    unittest.main()
