"""Phase B: effective Watchtower tools/list and catalog inspect cannot drift."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import Mock

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import (
    NODE_TOOLS, effective_catalog, make_server,
)
from tests.helpers.mcp_federation import FederationCatalogFixture, fixture_tool


class EffectiveCatalogTests(unittest.TestCase):
    @staticmethod
    def federation():
        return FederationCatalogFixture([
            fixture_tool("odoo__customer_search", read=True),
            fixture_tool("odoo__quotation_create"),
            fixture_tool("odoo__destructive_read", read=True, destructive=True),
        ], source="odoo")

    def test_effective_scopes_match_the_exact_projected_list(self):
        source = self.federation()
        private = [{"name": "github_workflow_runs", "inputSchema": {"type": "object"},
                    "annotations": {"readOnlyHint": True}}]
        for execution in (None, object()):
            with self.subTest(execution=bool(execution)):
                tools, projected = effective_catalog(
                    private, federation=source, execution=execution)
                self.assertEqual([t["name"] for t in tools],
                                 [r["name"] for r in projected["tools"]])
                self.assertEqual(projected["count"], len(tools))
                self.assertEqual(len({t["name"] for t in tools}), len(tools))
                for tool, row in zip(tools, projected["tools"]):
                    self.assertEqual(tool["securitySchemes"][0]["scopes"],
                                     [row["required_scope"]])
                    self.assertEqual(tool["_meta"]["securitySchemes"],
                                     tool["securitySchemes"])
                    self.assertNotIn("inputSchema", row)
                rows = {r["name"]: r for r in projected["tools"]}
                self.assertEqual(rows["odoo__customer_search"]["required_scope"], "gway:read")
                self.assertEqual(rows["odoo__quotation_create"]["required_scope"], "gway:execute")
                self.assertEqual(rows["odoo__destructive_read"]["required_scope"], "gway:execute")
                self.assertEqual(rows["odoo__customer_search"]["origin"], "federated")
                local = [t["name"] for t in NODE_TOOLS]
                self.assertEqual([t["name"] for t in tools[-len(local):]]
                                 if execution is None else
                                 [t["name"] for t in tools[-len(local)-6:-6]], local)
                self.assertEqual("node_exec" in rows, execution is not None)

    def test_upstream_shadow_and_duplicate_denied_equally(self):
        for name in ("mcp_catalog_inspect", "workspace_inspect", "node_exec"):
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "shadowed"):
                effective_catalog([{"name": name, "inputSchema": {"type": "object"}}],
                                  federation=self.federation())
        private = {"name": "github_workflow_runs", "inputSchema": {"type": "object"}}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            effective_catalog([private, private], federation=self.federation())

    def test_http_tools_list_and_inspect_have_identical_effective_catalog(self):
        """Real bearer HTTP handler, in-process fixed backend/federation only."""
        with tempfile.TemporaryDirectory() as home:
            registry = BearerRegistry(Path(home) / "tokens.sqlite")
            bearer = registry.issue()
            with make_server(("127.0.0.1", 0), BearerVerifier(registry.path),
                             "http://127.0.0.1:19011/mcp", "synthetic-backend",
                             federation=self.federation()) as gateway:
                # Both endpoints receive the same fixed backend tool catalog.
                private = [{"name": "github_workflow_runs",
                            "inputSchema": {"type": "object"},
                            "annotations": {"readOnlyHint": True}}]
                body = json.dumps({"jsonrpc": "2.0", "id": 1,
                                   "result": {"tools": private}}).encode()
                response = Mock()
                response.status = 200
                response.headers = {"Content-Type": "application/json"}
                response.read.side_effect = lambda *args: body
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                gateway.opener.open = Mock(return_value=response)
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = "http://127.0.0.1:%d/mcp" % gateway.server_port

                    def call(method, tool=None):
                        request = {"jsonrpc": "2.0", "id": 1, "method": method,
                                   "params": {} if tool is None else
                                   {"name": tool, "arguments": {}}}
                        req = Request(endpoint, json.dumps(request).encode(),
                                      {"Authorization": "Bearer " + bearer,
                                       "Content-Type": "application/json"}, method="POST")
                        with urlopen(req, timeout=3) as res:
                            self.assertEqual(res.status, 200)
                            return json.loads(res.read())["result"]

                    advertised = call("tools/list")["tools"]
                    inspected = json.loads(call("tools/call", "mcp_catalog_inspect")
                                           ["content"][0]["text"])
                    self.assertEqual([t["name"] for t in advertised],
                                     [r["name"] for r in inspected["tools"]])
                    self.assertEqual([t["securitySchemes"][0]["scopes"][0]
                                      for t in advertised],
                                     [r["required_scope"] for r in inspected["tools"]])
                    self.assertGreaterEqual(gateway.opener.open.call_count, 2)
                finally:
                    gateway.shutdown()
                    thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
