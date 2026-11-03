"""M2.1: bearer administration is exclusively a local CLI capability."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BearerCliIsolationTests(unittest.TestCase):
    def test_cli_registered_but_not_mcp_or_mobile(self):
        entry = (ROOT / "gway_remote" / "__main__.py").read_text()
        ast.parse(entry)
        self.assertIn('add_parser("bearer"', entry)
        self.assertIn('if args.command == "bearer"', entry)
        self.assertIn('sys.stdin.isatty() and sys.stdout.isatty()', entry)
        mcp = (ROOT / "gway_remote" / "mcp_agent.py").read_text()
        self.assertNotIn("bearer_issue", mcp)
        self.assertNotIn("bearer_revoke", mcp)
        self.assertNotIn("mcp_bearer", mcp)
        self.assertNotIn("gway:submit", (ROOT / "gway_remote" / "mcp_bearer.py").read_text().split("SCOPES =", 1)[1].split("\n", 1)[0])

    def test_remote_read_only_rpc_cannot_reach_token_administration(self):
        from gway_remote.mcp_bearer_gateway import inspect_rpc
        import json
        for tool in ("bearer", "bearer_issue", "bearer_revoke", "token_issue", "agent_submit"):
            message = json.dumps({"jsonrpc": "2.0", "id": 1,
                "method": "tools/call", "params": {"name": tool}}).encode()
            self.assertFalse(inspect_rpc(message))
        from gway_remote.mcp_agent import list_tools
        allowed = {item["name"] for item in list_tools()}
        self.assertFalse(allowed & {"bearer", "bearer_issue", "bearer_revoke"})
        self.assertEqual(len(allowed), 7)


if __name__ == "__main__":
    unittest.main()
