"""Repository GitHub tools must be federated, never Watchtower builtins."""

import json
import unittest

from gway_remote import mcp_agent
from gway_remote.mcp_bearer_gateway import ALLOWED_TOOLS, effective_catalog, inspect_rpc


RETIRED = {
    "github_workflow_runs",
    "github_workflow_status",
    "github_workflow_errors",
    "github_branch_effective_rules",
    "github_commit_checks",
}


class RepoRetirementTests(unittest.TestCase):
    def test_no_github_builtin_or_legacy_dispatch(self):
        self.assertFalse(RETIRED & ALLOWED_TOOLS)
        self.assertFalse(RETIRED & {tool["name"] for tool in mcp_agent.TOOLS})
        self.assertEqual({tool["name"] for tool in mcp_agent.TOOLS},
                         {"mcp_source_status"})
        for name in RETIRED:
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "mcp_tool_not_allowed"):
                mcp_agent.call_tool(name, {}, authorized_scope="read")

    def test_private_gateway_rejects_obsolete_builtins(self):
        for name in RETIRED:
            payload = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            })
            self.assertFalse(inspect_rpc(payload))

        # Federated tool names remain admitted by the routing syntax, not
        # elevated to the fixed builtins allowlist.
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "repo__github_workflow_runs", "arguments": {}},
        })
        self.assertTrue(inspect_rpc(payload))

    def test_old_upstream_catalog_does_not_resurrect_github_builtins(self):
        old = [{"name": name, "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": True}} for name in RETIRED]
        visible, projected = effective_catalog(old)
        self.assertFalse(RETIRED & {t["name"] for t in visible})
        self.assertFalse(RETIRED & {t["name"] for t in projected["tools"]})


if __name__ == "__main__":
    unittest.main()
