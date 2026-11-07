"""Regression tests for federated MCP execution authorization."""
import unittest
from unittest.mock import patch

from gway_remote import mcp_agent, mcp_http
from gway_remote.mcp_source_registry import SourceRegistration


READ = {"name": "lookup", "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True}}
WRITE = {"name": "update", "inputSchema": {"type": "object"}}


class TestFederatedExecution(unittest.TestCase):
    def setUp(self):
        self.registration = SourceRegistration("odoo", "a" * 40, "/usr/bin/true",
                                               ("/usr/bin/true",), "nobody", True)
        mcp_agent.configure_sources((self.registration,), {"odoo": []})

    def tearDown(self):
        mcp_agent.configure_sources((), {})

    def test_read_token_cannot_execute_provider(self):
        with patch.object(mcp_agent, "_live_source_catalogs", return_value={"odoo": [WRITE]}), \
             patch.object(mcp_agent, "call_source_tool") as invoke:
            with self.assertRaisesRegex(ValueError, "execute_scope_required"):
                mcp_agent.call_tool("odoo__update", {}, authorized_scope="read")
            invoke.assert_not_called()

    def test_execute_token_dispatches_provider(self):
        with patch.object(mcp_agent, "_live_source_catalogs", return_value={"odoo": [WRITE]}), \
             patch.object(mcp_agent, "call_source_tool", return_value={"content": []}) as invoke:
            mcp_agent.call_tool("odoo__update", {}, authorized_scope="execute")
            self.assertEqual(invoke.call_args.kwargs["authorized_scope"], "execute")

    def test_read_provider_still_works(self):
        with patch.object(mcp_agent, "_live_source_catalogs", return_value={"odoo": [READ]}), \
             patch.object(mcp_agent, "call_source_tool", return_value={"content": []}) as invoke:
            mcp_agent.call_tool("odoo__lookup", {}, authorized_scope="read")
            self.assertEqual(invoke.call_args.kwargs["authorized_scope"], "read")

    def test_disabled_provider_cannot_dispatch(self):
        disabled = SourceRegistration("odoo", "a" * 40, "/usr/bin/true",
                                      ("/usr/bin/true",), "nobody", False)
        mcp_agent.configure_sources((disabled,), {})
        with self.assertRaisesRegex(ValueError, "mcp_tool_not_allowed"):
            mcp_agent.call_tool("odoo__update", {}, authorized_scope="execute")

    def test_retired_builtin_submit_is_not_allowed(self):
        with self.assertRaisesRegex(ValueError, "mcp_tool_not_allowed"):
            mcp_agent.call_tool("agent_submit", {}, authorized_scope="read")

    def test_http_transport_defaults_to_read(self):
        with patch.object(mcp_agent, "call_tool", return_value={"content": []}) as invoke:
            mcp_http.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "odoo__lookup", "arguments": {}}})
            self.assertEqual(invoke.call_args.kwargs["authorized_scope"], "read")


if __name__ == "__main__":
    unittest.main()
