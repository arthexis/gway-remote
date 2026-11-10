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
    def test_bridge_envelope_contract_rejects_execute_scope(self):
        # Exercise the actual authenticated bridge validator, not only
        # SessionBridgeDispatch called directly.
        from gway_remote.mcp_bridge_contract import (
            InvalidBridgeRequest, validate_envelope,
        )
        envelope = {
            "version": 1,
            "request_id": "a" * 32,
            "principal": "read-principal",
            "audience": "gway-002",
            "operation": "workspace.inspect",
            "scope": "gway:read",
            "issued_at": 1000,
            "expires_at": 1030,
            "arguments": {"node": "gway-002", "repository": "owner/repo"},
        }
        self.assertEqual(
            validate_envelope(envelope, audience="gway-002", now=1001),
            envelope,
        )
        with self.assertRaises(InvalidBridgeRequest):
            validate_envelope(
                {**envelope, "scope": "gway:execute"},
                audience="gway-002",
                now=1001,
            )
        with self.assertRaises(InvalidBridgeRequest):
            validate_envelope(
                {**envelope, "audience": "gway-003"},
                audience="gway-002",
                now=1001,
            )

    def test_signed_bridge_reuses_existing_node_transport(self):
        from types import SimpleNamespace
        from gway_remote.mcp_bridge_transport import AuthenticatedBridge, canonical, sign
        from gway_remote.mcp_bridge_contract import InvalidBridgeRequest

        class Verifier:
            def verify(self, token, required_scope):
                return token == "trusted" and required_scope == "gway:read"

        class ReadTransport:
            node = SimpleNamespace(node="gway-002", host_key_sha256="a" * 64)

            def invoke(self, request):
                self.last_request = request
                return {
                    "node": request["node"],
                    "request_id": request["request_id"],
                    "result": {"node": request["node"], "repository": request["repository"],
                               "git": {"head": {"state": "observed", "value": "b" * 40}}},
                }

        read_transport = ReadTransport()
        execution = SimpleNamespace(relay=SimpleNamespace(transport=read_transport))
        handler = SessionBridgeDispatch(
            verifier=Verifier(), session_token="trusted",
            allowed_node=lambda token, node: node == "gway-002",
            read_principal=lambda token: "reader",
            execution=execution,
        )
        key = b"k" * 32
        bridge = AuthenticatedBridge(key, audience="gway-002", dispatch=handler)
        envelope = {
            "version": 1, "request_id": "a" * 32, "principal": "reader",
            "audience": "gway-002", "operation": "workspace.inspect",
            "scope": "gway:read", "issued_at": 1000, "expires_at": 1030,
            "arguments": {"node": "gway-002", "repository": "owner/repo"},
        }
        signed = canonical({"envelope": envelope, "signature": sign(key, envelope)})
        result = bridge.process(signed, now=1001)
        self.assertEqual(result["git"]["head"]["value"], "b" * 40)
        self.assertEqual(read_transport.last_request["operation"], "workspace_inspect")
        self.assertEqual(read_transport.last_request["node"], "gway-002")
        for change in (
            {"request_id": "c" * 32, "scope": "gway:execute"},
            {"request_id": "d" * 32, "audience": "gway-003"},
        ):
            changed = {**envelope, **change}
            with self.subTest(change=change), self.assertRaises(InvalidBridgeRequest):
                bridge.process(canonical({
                    "envelope": changed, "signature": sign(key, changed),
                }), now=1001)

    def test_http_gateway_has_no_local_inspect_fallback(self):
        # Exercise the real MCP handler without opening a listener or SSH.
        import io
        from email.message import Message
        from types import SimpleNamespace
        from gway_remote.mcp_bearer_gateway import Handler

        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "workspace_inspect",
                       "arguments": {"node": "gway-002", "repository": "owner/repo"}},
        }
        data = json.dumps(payload).encode("utf-8")
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(
            approved_sources={}, federation=None, bridge_transport=None,
            execution=None,
        )
        handler.headers = Message()
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = str(len(data))
        handler.rfile = io.BytesIO(data)
        handler.wfile = io.BytesIO()
        statuses = []
        handler.send_response = statuses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        with patch("gway_remote.mcp_workspace_inspect.inspect_authorized",
                   side_effect=AssertionError("local workspace inspection forbidden")) as local:
            handler._process_authenticated("trusted", True, False)
            local.assert_not_called()
        self.assertEqual(statuses, [200])
        reply = json.loads(handler.wfile.getvalue())
        result = reply["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(
            json.loads(result["content"][0]["text"])["code"],
            "workspace_inspection_unavailable",
        )

    def test_workspace_uses_same_node_transport_as_provider_reads(self):
        from types import SimpleNamespace
        class Verifier:
            def verify(self, token, required_scope):
                return token == "valid" and required_scope == "gway:read"
        class Transport:
            def invoke(self, request):
                self.request = request
                return {"node": request["node"], "request_id": request["request_id"],
                        "result": {"node": request["node"],
                                   "repository": request["repository"]}}
        transport = Transport()
        execution = SimpleNamespace(relay=SimpleNamespace(transport=transport))
        def make(exec_service):
            return SessionBridgeDispatch(
                verifier=Verifier(), session_token="valid",
                allowed_node=lambda token, node: node == "gway-001",
                read_principal=lambda token: "reader",
                execution=exec_service)
        envelope = {"audience": "gway-001", "scope": "gway:read",
                    "operation": "workspace.inspect", "principal": "reader",
                    "arguments": {"node": "gway-001", "repository": "owner/repo"}}
        self.assertEqual(make(execution)(envelope)["repository"], "owner/repo")
        self.assertEqual(transport.request["operation"], "workspace_inspect")
        with self.assertRaises(PermissionError):
            make(None)(envelope)
        with self.assertRaises(PermissionError):
            make(execution)({**envelope, "scope": "gway:execute"})

    def test_catalog_is_read_only(self):
        self.assertIn("workspace_inspect", ALLOWED_TOOLS)
        tool = next(tool for tool in NODE_TOOLS if tool["name"] == "workspace_inspect")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(tool["_meta"], READ_SECURITY)
        self.assertEqual(OPERATIONS["workspace_inspect"], ("workspace.inspect", "gway:read"))
        self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_unregistered_workspace_returns_explicit_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp)
            result = inspect_authorized(
                {"node": "gway-001", "repository": "arthexis/gway-remote"},
                trusted_node="gway-001", registry=registry,
                trusted_uid=os.geteuid(), discover=lambda: (),
            )
        self.assertEqual(result["git"]["head"]["state"], "unknown")
        self.assertEqual(result["git"]["head"]["reason"],
                         "repository_not_registered")
        self.assertEqual(result["deployment"]["state"], "unknown")

    def test_rejects_cross_node_and_extra_arguments(self):
        with self.assertRaises(PermissionError):
            inspect_authorized(
                {"node": "gway-002", "repository": "arthexis/gway-remote"},
                trusted_node="gway-001")
        with self.assertRaises(ValueError):
            inspect_authorized(
                {"node": "gway-001", "repository": "arthexis/gway-remote",
                 "path": "/tmp"}, trusted_node="gway-001")
        with self.assertRaises(ValueError):
            inspect_authorized({"node": "gway-001", "repository": "../etc"},
                               trusted_node="gway-001")

    def test_rejects_world_writable_registered_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp)
            policy = registry / "agentops.repositories"
            policy.write_text("arthexis/gway-remote")
            policy.chmod(0o666)
            result = inspect_authorized(
                {"node": "gway-001", "repository": "arthexis/gway-remote"},
                trusted_node="gway-001", registry=registry,
                trusted_uid=os.geteuid(), discover=lambda: (),
            )
        self.assertEqual(result["git"]["head"]["state"], "unknown")
        self.assertEqual(result["git"]["head"]["reason"],
                         "workspace_registry_invalid")

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
                                             "repository": request["repository"]},
                                            trusted_node="gway-001")
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
            from types import SimpleNamespace
            execution = (SimpleNamespace(relay=SimpleNamespace(transport=transport))
                         if transport is not None else None)
            return SessionBridgeDispatch(
                verifier=Verifier(), session_token="valid",
                allowed_node=lambda token, node: node == "gway-001",
                read_principal=lambda token: "reader", execution=execution)
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
