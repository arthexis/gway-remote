"""Loopback-only acceptance with synthetic providers."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server, effective_catalog, federated_source_status
from gway_remote.mcp_gateway_federation import FederatedProviders
from tests.helpers.mcp_http import bearer_post, mcp_call
from tests.test_mcp_multinode_federation import reply


class Transport:
    def __init__(self):
        self.sent = []
        self.offline = set()

    def invoke(self, node, request, *, trusted_scope):
        if node in self.offline:
            raise TimeoutError("offline")
        if request["operation"] == "provider_list":
            return reply(node)
        self.sent.append((node, request, trusted_scope))
        return {"ok": True, "node": node}


class CanonicalHTTPTests(unittest.TestCase):
    def test_catalog_and_dispatch(self):
        transport = Transport()
        federation = FederatedProviders(transport=transport,
            nodes=lambda: ("gway-001", "gway-004"), canonical=True)
        tools, projection = effective_catalog([], federation=federation)
        entries = {t["name"]: t for t in projection["tools"]}
        self.assertEqual(entries["agentops__status"]["nodes"], ["gway-001", "gway-004"])
        self.assertEqual(entries["agentops__status"]["required_scope"], "gway:read")
        self.assertTrue(entries["gway_004_agentops__status"]["legacy_alias"])
        self.assertIn("node", next(t for t in tools if t["name"] ==
            "agentops__submit")["inputSchema"]["required"])
        for source in federated_source_status(federation)["sources"]:
            self.assertEqual(source["tools"], ["agentops__status"])
            self.assertEqual(source["withheld_execute_count"], 1)
        with tempfile.TemporaryDirectory() as directory:
            registry = BearerRegistry(Path(directory) / "gateway.db")
            read = registry.issue()
            parent = registry.issue(scope="gway:execute", operator_approved=True)
            execute = registry.issue(scope="gway:execute", parent_id=parent.split("_", 2)[1])
            with make_server(("127.0.0.1", 0), BearerVerifier(registry.path),
                    "http://127.0.0.1:1/mcp", "synthetic",
                    federation=federation) as gateway:
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = "http://127.0.0.1:%d/mcp" % gateway.server_port
                    def call(name, args, token):
                        try:
                            with urlopen(bearer_post(endpoint, mcp_call(name, args), token),
                                         timeout=3) as response:
                                return response.status, json.loads(response.read())
                        except HTTPError as exc:
                            code = exc.code
                            exc.close()
                            return code, None
                    self.assertEqual(call("agentops__status", {"node": "gway-004"}, read)[0], 200)
                    self.assertEqual(transport.sent[-1], ("gway-004", {
                        "operation": "provider_read", "provider": "agentops",
                        "tool": "status", "arguments": {}}, "read"))
                    self.assertEqual(call("agentops__status", {}, read)[0], 200)
                    self.assertEqual(transport.sent[-1][0], "gway-001")
                    self.assertEqual(call("gway_004_agentops__status", {}, read)[0], 200)
                    self.assertEqual(transport.sent[-1][0], "gway-004")
                    for name, args, token, code in (
                        ("gway_004_agentops__status", {"node": "gway-001"}, read, 403),
                        ("agentops__submit", {"node": "gway-004"}, read, 401),
                        ("agentops__submit", {}, execute, 403),
                        ("agentops__status", {"node": "unknown"}, read, 403)):
                        before = len(transport.sent)
                        self.assertEqual(call(name, args, token)[0], code)
                        self.assertEqual(len(transport.sent), before)
                    self.assertEqual(call("agentops__submit", {"node": "gway-004"}, execute)[0], 200)
                    self.assertEqual(transport.sent[-1][0], "gway-004")
                    transport.offline.add("gway-004")
                    before = len(transport.sent)
                    self.assertEqual(call("agentops__status", {"node": "gway-004"}, read)[0], 403)
                    self.assertEqual(len(transport.sent), before)
                finally:
                    gateway.shutdown()
                    thread.join()

    def test_alias_retirement(self):
        federation = FederatedProviders(transport=Transport(),
            nodes=lambda: ("gway-001", "gway-004"), canonical=True, legacy_aliases=False)
        tools, routes = federation.discover()
        self.assertEqual(set(routes), {"agentops__status", "agentops__submit"})
        self.assertEqual(len(tools), 2)
