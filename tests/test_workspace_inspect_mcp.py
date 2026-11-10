"""MCP workspace inspection registration and fail-closed behavior."""
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.mcp_bearer_gateway import ALLOWED_TOOLS, NODE_TOOLS, READ_SECURITY
from gway_remote.mcp_bridge_gateway_dispatch import OPERATIONS
from gway_remote.mcp_workspace_inspect import inspect_authorized
from gway_remote.mcp_bridge_session import SessionBridgeDispatch
from gway_remote.node_exec_protocol import serve_one


class WorkspaceInspectMCPTests(unittest.TestCase):
    def test_catalog_is_read_only(self):
        self.assertIn("workspace_inspect", ALLOWED_TOOLS)
        tool = next(tool for tool in NODE_TOOLS if tool["name"] == "workspace_inspect")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(tool["_meta"], READ_SECURITY)
        self.assertEqual(OPERATIONS["workspace_inspect"], ("workspace.inspect", "gway:read"))
        self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_rejects_unconfigured_workspace(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PermissionError):
                inspect_authorized({"node": "gway-001", "repository": "arthexis/gway-remote"})

    def test_rejects_cross_node_and_extra_arguments(self):
        with patch.dict(os.environ, {"GWAY_WORKSPACE_NODE": "gway-001"}, clear=True):
            with self.assertRaises(PermissionError):
                inspect_authorized({"node": "gway-002", "repository": "owner/repo"})
            with self.assertRaises(ValueError):
                inspect_authorized({"node": "gway-001", "repository": "owner/repo", "path": "/tmp"})

    def test_rejects_world_writable_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "workspaces.json"
            config.write_text('{"owner/repo":"/tmp"}')
            config.chmod(0o666)
            with patch.dict(os.environ, {"GWAY_WORKSPACE_NODE": "gway-001",
                                         "GWAY_WORKSPACE_INSPECT_CONFIG": str(config)}):
                with self.assertRaises(PermissionError):
                    inspect_authorized({"node": "gway-001", "repository": "owner/repo"})

    def test_node_forced_protocol_accepts_only_fixed_read_operation(self):
        request = {"operation": "workspace_inspect", "node": "gway-001",
                   "request_id": "a" * 32, "repository": "arthexis/odoo-gelectriic"}
        with (patch("gway_remote.node_exec_protocol.require_account"),
              patch("gway_remote.mcp_workspace_inspect.inspect_authorized",
                    return_value={"node": "gway-001", "repository": request["repository"]}) as inspect):
            result = serve_one(json.dumps(request).encode(), hostname="gway-001")
            self.assertEqual(result["node"], "gway-001")
            self.assertEqual(result["request_id"], request["request_id"])
            inspect.assert_called_once_with({"node": "gway-001",
                                             "repository": request["repository"]})
            for invalid in ({**request, "path": "/etc/shadow"},
                            {**request, "node": "gway-002"},
                            {**request, "operation": "shell"}):
                with self.assertRaises((ValueError, PermissionError)):
                    serve_one(json.dumps(invalid).encode(), hostname="gway-001")

    def test_attested_transport_only_and_fail_closed(self):
        class Verifier:
            def verify(self, token, required_scope):
                return token == "valid" and required_scope == "gway:read"
        class Node:
            node = "gway-001"
            host_key_sha256 = "a" * 64
        class Pinned:
            node = Node()
            def invoke(self, request):
                return {"node": "gway-001", "request_id": request["request_id"],
                        "result": {"node": "gway-001", "repository": request["repository"],
                                   "git": {"head": {"state": "observed", "value": "b" * 40}}}}
        envelope = {"audience": "gway-001", "scope": "gway:read",
                    "operation": "workspace.inspect", "principal": "reader",
                    "arguments": {"node": "gway-001", "repository": "arthexis/odoo-gelectriic"}}
        def make(transport):
            return SessionBridgeDispatch(
                verifier=Verifier(), session_token="valid",
                allowed_node=lambda token, node: node == "gway-001",
                read_principal=lambda token: "reader", read_transport=transport)
        with self.assertRaises(PermissionError):
            make(None)(envelope)
        self.assertEqual(make(Pinned())(envelope)["git"]["head"]["value"], "b" * 40)
        with self.assertRaises(PermissionError):
            make(Pinned())({**envelope, "arguments": {**envelope["arguments"], "node": "gway-002"}})
        with self.assertRaises(PermissionError):
            make(Pinned())({**envelope, "audience": "gway-002"})
        class Spoofed(Pinned):
            def invoke(self, request):
                result = super().invoke(request)
                result["node"] = "gway-002"
                return result
        with self.assertRaises(PermissionError):
            make(Spoofed())(envelope)
        class Broken(Pinned):
            def invoke(self, request):
                raise TimeoutError("offline")
        with self.assertRaises(TimeoutError):
            make(Broken())(envelope)


if __name__ == "__main__":
    unittest.main()
