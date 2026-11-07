"""Provider-specific MCP error response tests."""
import json
import unittest
from unittest.mock import patch
from gway_remote import mcp_http, mcp_agent


class ProviderErrorsTest(unittest.TestCase):
    def call(self, name):
        return mcp_http.handle({"jsonrpc": "2.0", "id": 1,
                                "method": "tools/call",
                                "params": {"name": name, "arguments": {}}})

    def test_provider_failure_is_identified_without_leaking_message(self):
        with patch.object(mcp_agent, "call_tool", side_effect=RuntimeError(
                "secret-token /var/lib/odoo/private")):
            result, code, _ = self.call("odoo__contacts")
        self.assertIsNone(code)
        self.assertTrue(result["isError"])
        detail = json.loads(result["content"][0]["text"])
        self.assertEqual(detail["provider"], "odoo")
        self.assertEqual(detail["error_type"], "RuntimeError")
        self.assertNotIn("secret-token", str(result))
        self.assertNotIn("/var/lib", str(result))

    def test_builtin_failure_is_not_attributed_to_agentops(self):
        with patch.object(mcp_agent, "call_tool", side_effect=OSError("private path")):
            result, _, _ = self.call("github_workflow_runs")
        self.assertEqual(json.loads(result["content"][0]["text"])["provider"], "gway-remote")

    def test_scope_failure_is_explicit(self):
        with patch.object(mcp_agent, "call_tool", side_effect=ValueError(
                "mcp_execute_scope_required")):
            result, code, message = self.call("odoo__update")
        self.assertIsNone(result)
        self.assertEqual(code, -32602)
        self.assertEqual(message, "mcp_execute_scope_required")


if __name__ == "__main__":
    unittest.main()
