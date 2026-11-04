"""Loopback-only bearer gate for the read-only GWA MCP upstream.

Public Nginx activation and authenticated private transport are separate gates.
"""
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .mcp_bearer import BearerVerifier

MAX_BODY = 65536
MAX_RESPONSE = 262144
# Agent Ops read adapters may take 20 seconds; allow bounded bridge overhead.
UPSTREAM_TIMEOUT = 30
ALLOWED_METHODS = frozenset({"server/discover", "initialize", "notifications/initialized", "tools/list", "tools/call"})
ALLOWED_TOOLS = frozenset({"agent_list_issues", "agent_status", "agent_preview", "agent_observe",
    "github_workflow_runs", "github_workflow_status", "github_workflow_errors",
    "node_list", "node_capabilities", "node_exec_preview",
    "node_exec", "node_result", "node_cancel", "node_deploy", "node_deploy_status"})

EXEC_TOOL_NAMES = frozenset({"node_exec", "node_result", "node_cancel", "node_deploy", "node_deploy_status"})
EXEC_SECURITY = {"securitySchemes": [{"type": "oauth2", "scopes": ["gway:execute"]}]}
READ_SECURITY = {"securitySchemes": [{"type": "oauth2", "scopes": ["gway:read"]}]}

EXEC_TOOLS = (
    {"name": "node_deploy", "_meta": EXEC_SECURITY,
     "description": "Start the fixed, operator-owned gway-remote release service on gway-001; no arbitrary commands or sudo.",
     "inputSchema": {"type": "object", "properties": {
         "node": {"type": "string", "enum": ["gway-001"]},
         "application": {"type": "string", "enum": ["gway-remote"]},
         "request_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
         "required": ["node", "application", "request_id"], "additionalProperties": False}},
    {"name": "node_deploy_status", "_meta": EXEC_SECURITY,
     "description": "Read the state and result of the fixed gway-remote release service on gway-001.",
     "inputSchema": {"type": "object", "properties": {
         "node": {"type": "string", "enum": ["gway-001"]},
         "application": {"type": "string", "enum": ["gway-remote"]},
         "request_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
         "required": ["node", "application", "request_id"], "additionalProperties": False}},
    {"name":"node_exec", "_meta": EXEC_SECURITY, "description":"Run a command on an eligible node with an authorized execute-scoped connection.",
     "inputSchema":{"type":"object","properties":{
         "node":{"type":"string"},"command":{"type":"string","maxLength":4096},
         "request_id":{"type":"string","pattern":"^[0-9a-f]{32}$"}},
         "required":["node","command","request_id"],"additionalProperties":False}},
    {"name":"node_result", "_meta": EXEC_SECURITY, "description":"Read the requester's bounded remote job result.",
     "inputSchema":{"type":"object","properties":{
         "request_id":{"type":"string"},"cursor":{"type":"integer","minimum":0}},
         "required":["request_id"],"additionalProperties":False}},
    {"name":"node_cancel", "_meta": EXEC_SECURITY, "description":"Cancel the requester's remote job.",
     "inputSchema":{"type":"object","properties":{"request_id":{"type":"string"}},
         "required":["request_id"],"additionalProperties":False}},
)

NODE_TOOLS = (
    {"name": "node_list", "_meta": READ_SECURITY, "description": "List active enrolled nodes from Watchtower (read-only; reachability unknown).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "node_capabilities", "_meta": READ_SECURITY, "description": "Inspect registration capability for one enrolled node; no command execution.",
     "inputSchema": {"type": "object", "properties": {"node": {"type": "string"}},
                     "required": ["node"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "node_exec_preview", "_meta": READ_SECURITY, "description": "Preview a shell command for an attested node; never executes.",
     "inputSchema": {"type": "object",
                     "properties": {"node": {"type": "string"}, "command": {"type": "string", "maxLength": 4096}},
                     "required": ["node", "command"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
)

AUTH_CHALLENGE = (
    'Bearer resource_metadata="https://remote.arthexis.com/.well-known/oauth-protected-resource/mcp", '
    'scope="gway:execute", error="insufficient_scope", '
    'error_description="Execution requires gway:execute authorization"'
)


def scoped_tool(tool, scheme):
    """Mirror the standard securitySchemes top-level and in _meta for compatibility."""
    security = scheme["securitySchemes"]
    return {**tool, "securitySchemes": security,
            "_meta": {**tool.get("_meta", {}), "securitySchemes": security}}


def local_node_result(method, arguments, *, execution=None):
    """Only inventory operations, never a shell or user-supplied address."""
    from . import node_registry_inventory
    if method == "node_list" and arguments == {}:
        return node_registry_inventory.public_nodes(execution_enabled=execution is not None)
    if method == "node_capabilities" and type(arguments) is dict and set(arguments) == {"node"}:
        return node_registry_inventory.capabilities(arguments["node"], execution_enabled=execution is not None)
    if method == "node_exec_preview" and type(arguments) is dict and set(arguments) == {"node", "command"}:
        from .node_exec_contract import preview
        inventory = node_registry_inventory.public_nodes(execution_enabled=execution is not None)
        # Only query the already-pinned, operator-enabled node; never accept an
        # address or host selector from the MCP request.
        concurrency = None
        if execution is not None and arguments["node"] == execution.relay.transport.node.node:
            try:
                import secrets
                observed = execution.relay.transport.invoke({
                    "operation": "limits", "node": arguments["node"],
                    "request_id": secrets.token_hex(16)})
                value = observed.get("concurrent_jobs_per_node")
                if type(value) is int and 1 <= value <= 8:
                    concurrency = value
            except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError):
                pass  # Unavailable is not the same as the legacy static value.
        return preview(arguments["node"], arguments["command"], inventory,
                       effective_concurrency=concurrency)
    raise ValueError("invalid node inventory arguments")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def payload_is_exec(raw):
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return False
    return (type(payload) is dict and payload.get("method") == "tools/call"
            and type(payload.get("params")) is dict
            and payload["params"].get("name") in EXEC_TOOL_NAMES)

def inspect_rpc(raw):
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return False
    if type(data) is not dict or data.get("jsonrpc") != "2.0":
        return False
    method = data.get("method")
    if method not in ALLOWED_METHODS:
        return False
    if method == "tools/call":
        params = data.get("params")
        return type(params) is dict and params.get("name") in ALLOWED_TOOLS
    return True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reject(self, status, *, scope=None):
        self.send_response(status)
        if status == 401:
            # Default ChatGPT connection is an operator connection: request
            # execute from the first OAuth handshake. Execute credentials
            # already authorize read-only tools; no mid-session switching.
            # Explicit gway:read OAuth clients still work with read credentials.
            challenge = ('Bearer resource_metadata="https://remote.arthexis.com/.well-known/oauth-protected-resource/mcp", '
                         'scope="gway:execute"')
            if scope == "gway:execute":
                challenge += ', error="insufficient_scope"'
            self.send_header("WWW-Authenticate", challenge)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.reject(405)

    def do_POST(self):
        if self.path != "/mcp":
            return self.reject(404)
        if self.headers.get("Origin") is not None:
            return self.reject(403)
        if len(self.headers.get_all("Authorization", [])) != 1:
            return self.reject(401)
        supplied = self.headers.get("Authorization", "")
        if not supplied.startswith("Bearer "):
            return self.reject(401)
        token = supplied[7:]
        has_read = self.server.registry.verify(token)
        has_exec = self.server.registry.verify(token, required_scope="gway:execute")
        if not (has_read or has_exec):
            return self.reject(401)
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self.reject(415)
        if (self.headers.get("Transfer-Encoding") is not None
                or len(self.headers.get_all("Content-Length", [])) != 1
                or len(self.headers.get_all("Content-Type", [])) != 1):
            return self.reject(400)
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.reject(413)
        if not 0 < length <= MAX_BODY:
            return self.reject(413)
        raw = self.rfile.read(length)
        if not inspect_rpc(raw):
            return self.reject(403)
        # Only a valid read credential reaches here. Missing execute scope
        # triggers the MCP tool-level OAuth UI without dispatching anything.
        # Keep all transport and RPC validation before returning a challenge.

        # Forward protocol metadata only after parsing the RPC. Never pass
        # arbitrary client-controlled headers to the private backend.
        payload = json.loads(raw)
        version = self.headers.get("MCP-Protocol-Version", "2025-03-26")
        if version not in ("2025-03-26", "2026-07-28"):
            return self.reject(400)
        if version == "2026-07-28":
            meta = payload.get("params", {}).get("_meta") if type(payload.get("params")) is dict else None
            if not isinstance(meta, dict) or meta.get("io.modelcontextprotocol/protocolVersion") != version:
                return self.reject(400)
        if payload["method"] == "tools/call" and payload.get("params", {}).get("name") in EXEC_TOOL_NAMES:
            params = payload.get("params", {})
            args = params.get("arguments", {})
            if not has_exec:
                denied = {
                    "content": [{"type": "text",
                                 "text": "Execution requires gway:execute authorization."}],
                    "isError": True,
                    "_meta": {"mcp/www_authenticate": [AUTH_CHALLENGE]}
                }
                if version == "2026-07-28":
                    denied = {"resultType": "complete", **denied}
                body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"),
                                   "result": denied}, separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("MCP-Protocol-Version", version)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.server.execution is None or type(args) is not dict:
                return self.reject(403)
            name = params["name"]
            try:
                principal = self.server.registry.execution_principal(token)
                if name == "node_exec" and set(args) == {"node","command","request_id"}:
                    selected = self.server.execution.exec(principal=principal, **args)
                elif name in ("node_deploy", "node_deploy_status") and set(args) == {"node", "application", "request_id"}:
                    selected = self.server.execution.deployment(
                        principal=principal, status=name == "node_deploy_status", **args)
                elif name == "node_result" and set(args).issubset({"request_id","cursor"}) and "request_id" in args:
                    selected = self.server.execution.result(principal=principal, **args)
                elif name == "node_cancel" and set(args) == {"request_id"}:
                    selected = self.server.execution.cancel(principal=principal, **args)
                else:
                    raise ValueError("invalid tool arguments")
                result = {"content":[{"type":"text","text":json.dumps(selected,separators=(",",":"))}]}
            except (PermissionError, ValueError, RuntimeError, OSError, TypeError, KeyError):
                result = {"content":[{"type":"text","text":"Execution request rejected"}],"isError":True}
            if version == "2026-07-28":
                result = {"resultType":"complete", **result}
            body = json.dumps({"jsonrpc":"2.0","id":payload.get("id"),"result":result},
                              separators=(",",":")).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("MCP-Protocol-Version",version)
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if payload["method"] == "tools/call" and payload.get("params", {}).get("name") in {"node_list", "node_capabilities", "node_exec_preview"}:
            # The enrollment ledger lives on Watchtower. Never pass these tools
            # to gway-001, and never grant the gateway access to the root DB.
            arguments = payload["params"].get("arguments", {})
            try:
                selected = local_node_result(payload["params"]["name"], arguments, execution=self.server.execution)
                result = {"content": [{"type": "text", "text": json.dumps(selected, separators=(",", ":"))}]}
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                result = {"content": [{"type": "text", "text": "Node inventory unavailable"}],
                          "isError": True}
            if version == "2026-07-28":
                result = {"resultType": "complete", **result}
            body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"), "result": result},
                              separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("MCP-Protocol-Version", version)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if version == "2026-07-28" and payload["method"] == "server/discover":
            result = {"resultType": "complete",
                      "supportedVersions": ["2026-07-28", "2025-03-26"],
                      "capabilities": {"tools": {}},
                      "_meta": {"io.modelcontextprotocol/serverInfo":
                                {"name": "gway-agent-ops", "version": "0.1.0"}}}
            body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"),
                               "result": result}, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("MCP-Protocol-Version", version)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # The field backend may still run legacy MCP. Adapt modern metadata
        # and complete results in this boundary without changing gway-001.
        adapt_modern = version == "2026-07-28"
        if adapt_modern:
            legacy_params = payload.get("params", {})
            if type(legacy_params) is dict:
                legacy_params = {k: v for k, v in legacy_params.items() if k != "_meta"}
            legacy_payload = {**payload, "params": legacy_params}
            raw = json.dumps(legacy_payload, separators=(",", ":")).encode("utf-8")
        # Forward only to a fixed private endpoint; never forward client headers.
        headers = {"Authorization": "Bearer " + self.server.backend_token,
                   "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-03-26"}
        req = Request(self.server.upstream, raw, headers, method="POST")
        try:
            with self.server.opener.open(req, timeout=UPSTREAM_TIMEOUT) as response:
                status = response.status
                body = response.read(MAX_RESPONSE + 1)
                typ = response.headers.get("Content-Type", "application/json")
        except HTTPError as exc:
            status, body, typ = exc.code, b"", "application/json"
            exc.close()
        except (OSError, URLError, ValueError):
            return self.reject(502)
        if len(body) > MAX_RESPONSE:
            return self.reject(502)
        if status not in (200, 202):
            return self.reject(502)
        if status == 200 and payload["method"] == "tools/list":
            # Merge the seven existing private tools with two Watchtower-local
            # registry views. Do not let upstream override or shadow them.
            try:
                upstream_payload = json.loads(body)
                result = upstream_payload["result"]
                tools = result["tools"]
                if (type(tools) is not list or
                        any(type(tool) is not dict or tool.get("name") in
                            ({"node_list", "node_capabilities", "node_exec_preview"} | EXEC_TOOL_NAMES) for tool in tools)):
                    raise ValueError("upstream tool collision")
                scoped_tools = [scoped_tool(tool, READ_SECURITY) for tool in tools]
                node_tools = [scoped_tool(tool, READ_SECURITY) for tool in NODE_TOOLS]
                exec_tools = [scoped_tool(tool, EXEC_SECURITY) for tool in EXEC_TOOLS]
                result["tools"] = (scoped_tools + node_tools +
                                   (exec_tools if self.server.execution is not None else []))
                body = json.dumps(upstream_payload, separators=(",", ":")).encode()
            except (ValueError, TypeError, KeyError, UnicodeError):
                return self.reject(502)
            if len(body) > MAX_RESPONSE:
                return self.reject(502)
        if adapt_modern and status == 200:
            try:
                upstream_payload = json.loads(body)
                if type(upstream_payload) is not dict:
                    raise ValueError("not an RPC reply")
                result = upstream_payload.get("result")
                if type(result) is dict and "resultType" not in result:
                    upstream_payload["result"] = {"resultType": "complete", **result}
                body = json.dumps(upstream_payload, separators=(",", ":")).encode()
                typ = "application/json"
            except (ValueError, UnicodeError):
                return self.reject(502)
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("MCP-Protocol-Version", version)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def make_server(address, registry, upstream, backend_token, *, execution=None):
    from urllib.parse import urlsplit
    parsed = urlsplit(upstream)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path != "/mcp" or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("private_loopback_upstream_required")
    if address[0] != "127.0.0.1":
        raise ValueError("loopback_bind_required")
    if not backend_token:
        raise ValueError("backend_secret_required")
    server = ThreadingHTTPServer(address, Handler)
    server.registry = registry
    server.execution = execution
    server.upstream = upstream
    server.backend_token = backend_token
    server.opener = build_opener(NoRedirect())
    return server

def main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--port", type=int, default=19010)
    parser.add_argument("--upstream", default="http://127.0.0.1:19011/mcp")
    args = parser.parse_args()
    token = os.environ.get("GWAY_MCP_BACKEND_BEARER", "")
    execution = None
    if os.environ.get("GWAY_MCP_EXEC_ENABLED") == "1":
        from .watchtower_exec_service import load_service
        execution = load_service()
    with make_server(("127.0.0.1", args.port), BearerVerifier(args.database), args.upstream,
                     token, execution=execution) as service:
        service.serve_forever()

if __name__ == "__main__":
    main()
