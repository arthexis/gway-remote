"""Loopback-only bearer gate for the read-only GWA MCP upstream.

Public Nginx activation and authenticated private transport are separate gates.
"""
import json
import os
import re
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
ALLOWED_TOOLS = frozenset({"github_workflow_runs", "github_workflow_status", "github_workflow_errors", "mcp_source_status",
    "node_list", "node_capabilities", "node_exec_preview",
    "node_exec", "node_result", "node_cancel", "node_deploy", "node_deploy_status",
    "node_deploy_preview", "workspace_inspect", "mcp_catalog_inspect"})

EXEC_TOOL_NAMES = frozenset({"node_exec", "node_result", "node_cancel", "node_deploy", "node_deploy_status"})
EXEC_SECURITY = {"securitySchemes": [{"type": "oauth2", "scopes": ["gway:execute"]}]}
READ_SECURITY = {"securitySchemes": [{"type": "oauth2", "scopes": ["gway:read"]}]}

EXEC_TOOLS = (
    {"name": "node_deploy", "_meta": EXEC_SECURITY,
     "description": "Start an allowlisted Ansible deployment on an attested node using a fixed root-owned service. No arbitrary shell, path, or options.",
     "inputSchema": {"type": "object", "properties": {
         "node": {"type": "string"},
         "application": {"type": "string"},
         "revision": {"type": "string", "enum": ["main"]},
         "request_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
         "required": ["node", "application", "request_id"], "additionalProperties": False}},
    {"name": "node_deploy_status", "_meta": EXEC_SECURITY,
     "description": "Read the installed fixed deployment service receipt on the selected attested node; use node_result for the returned request ID.",
     "inputSchema": {"type": "object", "properties": {
         "node": {"type": "string"},
         "application": {"type": "string"},
         "revision": {"type": "string", "enum": ["main"]},
         "request_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
         "required": ["node", "application", "request_id"], "additionalProperties": False}},
    {"name":"node_exec", "_meta": EXEC_SECURITY, "description":"Run a command on an eligible node; return short job results inline, or a request_id for longer jobs.",
     "inputSchema":{"type":"object","properties":{
         "node":{"type":"string"},"command":{"type":"string","maxLength":4096},
         "request_id":{"type":"string","pattern":"^[0-9a-f]{32}$"},
         "wait_seconds":{"type":"integer","minimum":0,"maximum":10}},
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
    {"name": "mcp_catalog_inspect", "_meta": READ_SECURITY,
     "description": "Inspect the live Watchtower federated MCP catalog, origin and required OAuth scope; never returns credentials or executes tools.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "workspace_inspect", "_meta": READ_SECURITY,
     "description": "Inspect an allowlisted repository on the authenticated node; unknown evidence is explicit.",
     "inputSchema": {"type": "object", "properties": {
         "node": {"type": "string"}, "repository": {"type": "string"}},
         "required": ["node", "repository"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "node_deploy_preview", "_meta": READ_SECURITY,
     "description": "Check a fixed Ansible deployment recipe and current node eligibility without executing.",
     "inputSchema": {"type": "object", "properties": {
         "node": {"type": "string"},
         "application": {"type": "string"},
         "revision": {"type": "string", "enum": ["main"]}},
         "required": ["node", "application"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
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
    if method == "node_deploy_preview" and type(arguments) is dict and \
            {"node", "application"} <= set(arguments) and \
            set(arguments) <= {"node", "application", "revision"}:
        if execution is None:
            raise PermissionError("deployment unavailable")
        return execution.deployment_preview(**arguments)
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
        if execution is not None and (arguments["node"] in execution.relay.transport.transports if hasattr(execution.relay.transport, "transports") else arguments["node"] == execution.relay.transport.node.node):
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

SOURCE_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}__[a-z][a-z0-9_]{0,63}$")


def federated_source_status(federation):
    """Summarize the exact node-federated routes, without exposing transport details."""
    _, routes = federation.discover()
    sources = {}
    for name in sorted(routes):
        node, source, _, scope = routes[name]
        item = sources.setdefault((node, source), {
            "source": source, "node": node, "enabled": True,
            "status": "available", "tools": [],
            "withheld_execute_count": 0})
        if scope == "read":
            item["tools"].append(name)
        else:
            item["withheld_execute_count"] += 1
    return {"sources": list(sources.values()),
            "registered_count": len(sources),
            "discovery": "node_federation"}


def inspect_federated_catalog(federation, *, builtins=()):
    """Describe the live node-owned catalog with no credentials or provider arguments."""
    catalog, routes = federation.discover(builtins=builtins)
    rows = []
    for tool in catalog:
        name = tool["name"]
        route = routes.get(name)
        scope = route[3] if route else ("execute" if name in EXEC_TOOL_NAMES else "read")
        rows.append({"name": name, "origin": "federated" if route else "builtin",
                     "node": route[0] if route else None,
                     "source": route[1] if route else None,
                     "classification": scope,
                     "required_scope": "gway:execute" if scope == "execute" else "gway:read"})
    return {"schema": 1, "discovery": "node_federation", "tools": rows,
            "count": len(rows)}


def trusted_source_tool(tool):
    """Backend admits the provider; annotations declare the tool scope."""
    return (type(tool) is dict and type(tool.get('name')) is str
            and SOURCE_TOOL_NAME.fullmatch(tool['name']) is not None
            and type(tool.get('inputSchema')) is dict)


def inspect_rpc(raw, approved_sources=()):
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
        return type(params) is dict and (params.get("name") in ALLOWED_TOOLS or
                (type(params.get("name")) is str and SOURCE_TOOL_NAME.fullmatch(params["name"]) is not None))
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
        if self.server.bridge_sessions is None:
            return self._process_authenticated(token, has_read, has_exec)
        from .mcp_bridge_gateway_session import gateway_bridge_session
        try:
            with gateway_bridge_session(
                    self.server.bridge_sessions, bearer=token,
                    audience="gway-001") as session_id:
                self.bridge_session_id = session_id
                return self._process_authenticated(token, has_read, has_exec)
        except (PermissionError, ValueError, RuntimeError):
            return self.reject(403)

    def _bridge_node_tool(self, name, arguments, token):
        from .mcp_bridge_gateway_dispatch import dispatch_node_tool, OPERATIONS
        if self.server.bridge_sessions is None or not hasattr(self, "bridge_session_id"):
            raise PermissionError("bridge session missing")
        operation, scope = OPERATIONS[name]
        if not self.server.registry.verify(token, required_scope=scope):
            raise PermissionError("insufficient bridge scope")
        if scope == "gway:execute":
            principal = self.server.registry.execution_principal(token)
        else:
            principal = self.server.bridge_sessions.read_principal(token)
        path, key, audience = self.server.bridge_transport
        return dispatch_node_tool(
            socket_path=path, key=key, session_id=self.bridge_session_id,
            audience=audience, principal=principal, name=name,
            arguments=arguments)

    def _process_authenticated(self, token, has_read, has_exec):
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
        if not inspect_rpc(raw, self.server.approved_sources):
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
        # Report the same node-owned federation used by tools/list, not the
        # legacy upstream source policy. This makes missing node transport
        # visible without revealing endpoints, credentials or manifests.
        if (payload["method"] == "tools/call" and
                payload.get("params", {}).get("name") == "mcp_source_status" and
                self.server.federation is not None):
            try:
                selected = federated_source_status(self.server.federation)
                result = {"content": [{"type": "text",
                                      "text": json.dumps(selected, separators=(",", ":"))}]}
                if version == "2026-07-28":
                    result = {"resultType": "complete", **result}
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
            except (ValueError, PermissionError, RuntimeError, OSError, TypeError, KeyError):
                return self.reject(502)
        if (payload["method"] == "tools/call" and
                payload.get("params", {}).get("name") == "mcp_catalog_inspect"):
            try:
                if payload["params"].get("arguments", {}) != {} or self.server.federation is None:
                    raise ValueError("invalid catalog request")
                # Read the same private backend builtins as tools/list, then
                # apply the same allowlist before composing the live federation.
                probe = json.dumps({"jsonrpc": "2.0", "id": 0,
                                    "method": "tools/list", "params": {}}).encode()
                headers = {"Authorization": "Bearer " + self.server.backend_token,
                           "Content-Type": "application/json",
                           "Accept": "application/json, text/event-stream",
                           "MCP-Protocol-Version": "2025-03-26"}
                with self.server.opener.open(Request(self.server.upstream, probe,
                                                     headers), timeout=UPSTREAM_TIMEOUT) as upstream:
                    backend_tools = json.loads(upstream.read())["result"]["tools"]
                if type(backend_tools) is not list:
                    raise ValueError("invalid backend catalog")
                builtin_names = {tool["name"] for tool in NODE_TOOLS + EXEC_TOOLS}
                if any(type(tool) is not dict or type(tool.get("name")) is not str
                       or tool["name"] in builtin_names for tool in backend_tools):
                    raise ValueError("invalid backend tools")
                backend_tools = [tool for tool in backend_tools
                                 if tool["name"] in ALLOWED_TOOLS]
                selected = inspect_federated_catalog(
                    self.server.federation,
                    builtins=backend_tools + list(NODE_TOOLS) +
                    (list(EXEC_TOOLS) if self.server.execution is not None else []))
                result = {"content": [{"type": "text",
                                      "text": json.dumps(selected, separators=(",", ":"))}]}
                if version == "2026-07-28":
                    result = {"resultType": "complete", **result}
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
            except (ValueError, RuntimeError, OSError, TypeError, KeyError, URLError, HTTPError):
                return self.reject(502)
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
                if self.server.bridge_transport is not None:
                    selected = self._bridge_node_tool(name, args, token)
                elif name == "node_exec" and {"node","command","request_id"}.issubset(args) and set(args).issubset({"node","command","request_id","wait_seconds"}):
                    selected = self.server.execution.exec(principal=principal, **args)
                elif name in ("node_deploy", "node_deploy_status") and {"node", "application", "request_id"} <= set(args) and set(args) <= {"node", "application", "request_id", "revision"}:
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
        if payload["method"] == "tools/call" and payload.get("params", {}).get("name") in {"node_list", "node_capabilities", "node_exec_preview", "node_deploy_preview", "workspace_inspect"}:
            # The enrollment ledger lives on Watchtower. Never pass these tools
            # to gway-001, and never grant the gateway access to the root DB.
            arguments = payload["params"].get("arguments", {})
            try:
                if self.server.bridge_transport is not None:
                    selected = self._bridge_node_tool(
                        payload["params"]["name"], arguments, token)
                elif payload["params"]["name"] == "workspace_inspect":
                    from .mcp_workspace_inspect import inspect_authorized
                    selected = inspect_authorized(arguments)
                else:
                    selected = local_node_result(payload["params"]["name"], arguments, execution=self.server.execution)
                result = {"content": [{"type": "text", "text": json.dumps(selected, separators=(",", ":"))}]}
            except (OSError, ValueError, PermissionError, KeyError, TypeError, json.JSONDecodeError):
                result = {"content": [{"type": "text", "text": "Node inventory or deployment preview unavailable"}],
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
        # Validate source calls against the live trusted backend catalog. A
        # namespaced name alone is not authorization: unregistered tools fail closed.
        if (self.server.federation is None and payload["method"] == "tools/call"
                and SOURCE_TOOL_NAME.fullmatch(payload["params"]["name"])):
            probe = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "tools/list",
                                "params": {}}, separators=(",", ":")).encode()
            probe_headers = {"Authorization": "Bearer " + self.server.backend_token,
                             "Content-Type": "application/json",
                             "Accept": "application/json, text/event-stream",
                             "MCP-Protocol-Version": "2025-03-26"}
            try:
                with self.server.opener.open(Request(self.server.upstream, probe,
                        probe_headers, method="POST"), timeout=UPSTREAM_TIMEOUT) as response:
                    if response.status != 200:
                        return self.reject(502)
                    listed = json.loads(response.read(MAX_RESPONSE + 1))["result"]["tools"]
                matching = [tool for tool in listed if trusted_source_tool(tool)
                            and tool["name"] == payload["params"]["name"]]
                if len(matching) != 1:
                    return self.reject(403)
                annotations = matching[0].get("annotations", {})
                is_read = (type(annotations) is dict and annotations.get("readOnlyHint") is True
                           and annotations.get("destructiveHint") is not True)
                if not is_read and not has_exec:
                    return self.reject(401, scope="gway:execute")
            except (OSError, URLError, HTTPError, ValueError, TypeError, KeyError):
                return self.reject(502)
        # Federated providers are resolved from attested nodes, not Watchtower policy.
        # The federation object is provisioned by the trusted service bootstrap.
        if payload["method"] == "tools/call" and SOURCE_TOOL_NAME.fullmatch(
                payload.get("params", {}).get("name", "")):
            if self.server.federation is None:
                return self.reject(403)
            try:
                name = payload["params"]["name"]
                arguments = payload["params"].get("arguments", {})
                if type(arguments) is not dict:
                    return self.reject(400)
                _, routes = self.server.federation.discover()
                if name not in routes:
                    return self.reject(403)
                if routes[name][3] == "execute" and not has_exec:
                    return self.reject(401, scope="gway:execute")
                selected = self.server.federation.call(
                    name, arguments, authorized_scope="execute" if has_exec else "read")
                result = {"content": [{"type": "text", "text": json.dumps(selected, separators=(",", ":"))}]}
                body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"),
                                   "result": {"resultType": "complete", **result}
                                   if version == "2026-07-28" else result},
                                  separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("MCP-Protocol-Version", version)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            except (ValueError, PermissionError, RuntimeError, OSError, TypeError, KeyError):
                return self.reject(403)
        # Forward only to a fixed private endpoint; never forward client headers.
        headers = {"Authorization": "Bearer " + self.server.backend_token,
                   "X-Gway-Caller-Scope": "execute" if has_exec else "read",
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
                            ({"node_list", "node_capabilities", "node_exec_preview", "node_deploy_preview"} | EXEC_TOOL_NAMES) for tool in tools)):
                    raise ValueError("upstream tool collision")
                # Source admission is authoritative on the trusted backend.
                # Watchtower does not maintain a second per-tool allowlist.
                names = [tool.get("name") for tool in tools]
                if any(type(name) is not str for name in names) or len(names) != len(set(names)):
                    raise ValueError("invalid upstream tool names")
                tools = [tool for tool in tools if tool["name"] in ALLOWED_TOOLS]
                if self.server.federation is not None:
                    remote_tools, _ = self.server.federation.discover(builtins=tools + list(NODE_TOOLS) + list(EXEC_TOOLS))
                    # Node registrations are authoritative; no Watchtower
                    # per-provider allowlist or static tool approval.
                    builtin_names = {tool["name"] for tool in NODE_TOOLS + EXEC_TOOLS}
                    tools = [tool for tool in remote_tools if tool["name"] not in builtin_names]
                scoped_tools = [scoped_tool(tool, EXEC_SECURITY if (trusted_source_tool(tool) and not (
                                 type(tool.get("annotations")) is dict and
                                 tool["annotations"].get("readOnlyHint") is True and
                                 tool["annotations"].get("destructiveHint") is not True)) else READ_SECURITY) for tool in tools]
                node_tools = [scoped_tool(tool, READ_SECURITY) for tool in NODE_TOOLS]
                exec_tools = [scoped_tool(tool, EXEC_SECURITY) for tool in EXEC_TOOLS]
                result["tools"] = (scoped_tools + node_tools +
                                   (exec_tools if self.server.execution is not None else []))
                body = json.dumps(upstream_payload, separators=(",", ":")).encode()
            except (ValueError, TypeError, KeyError, UnicodeError, OSError, RuntimeError, TimeoutError):
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

def make_server(address, registry, upstream, backend_token, *, execution=None, bridge_sessions=None, bridge_transport=None, approved_sources=None, federation=None):
    from urllib.parse import urlsplit
    parsed = urlsplit(upstream)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path != "/mcp" or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("private_loopback_upstream_required")
    if address[0] != "127.0.0.1":
        raise ValueError("loopback_bind_required")
    if not backend_token:
        raise ValueError("backend_secret_required")
    server = ThreadingHTTPServer(address, Handler)
    # Policy is supplied by trusted provisioning, never learned from the upstream response.
    approved_sources = {} if approved_sources is None else dict(approved_sources)
    for name, tool in approved_sources.items():
        if (type(name) is not str or "__" not in name or name in ALLOWED_TOOLS
                or type(tool) is not dict or tool.get("name") != name
                or type(tool.get("annotations")) is not dict
                or tool["annotations"].get("readOnlyHint") is not True
                or tool["annotations"].get("destructiveHint") is True):
            raise ValueError("invalid approved source policy")
    server.approved_sources = approved_sources
    server.federation = federation
    server.registry = registry
    server.execution = execution
    if bridge_transport is not None and bridge_sessions is None:
        raise ValueError("bridge transport requires session manager")
    server.bridge_sessions = bridge_sessions
    server.bridge_transport = bridge_transport
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
    federation = None
    if execution is not None:
        from .mcp_gateway_federation import FederatedProviders
        from .mcp_provider_transport import ProviderTransport
        transport = execution.relay.transport
        federation = FederatedProviders(
            transport=ProviderTransport(transport),
            nodes=lambda: tuple(transport.transports) if hasattr(transport, "transports")
            else (transport.node.node,))
    policy_path = os.environ.get("GWAY_MCP_SOURCE_POLICY")
    policy_sha = os.environ.get("GWAY_MCP_SOURCE_POLICY_SHA256")
    if bool(policy_path) != bool(policy_sha):
        raise ValueError("incomplete source policy configuration")
    approved_sources = None
    if policy_path and federation is None:
        from .mcp_source_policy import load_source_policy
        from .mcp_source_registry import compose_source_catalog
        registrations, approved = load_source_policy(
            policy_path, expected_sha256=policy_sha)
        catalog = compose_source_catalog([], registrations, approved)
        approved_sources = {tool["name"]: tool for tool in catalog}
    verifier = BearerVerifier(args.database)
    from .mcp_bridge_bootstrap import start_bridge
    import signal
    previous_term = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    started = None
    try:
        # Keep SIGTERM pending until the newly created bridge has a cleanup owner.
        # The pending signal is delivered only after 'started' is assigned.
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            started = start_bridge(verifier, execution=execution)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        options = {}
        if started is not None:
            _, _, sessions, transport = started
            options = {"bridge_sessions": sessions, "bridge_transport": transport}
        with make_server(("127.0.0.1", args.port), verifier, args.upstream,
                         token, execution=execution, approved_sources=approved_sources,
                         federation=federation, **options) as service:
            service.serve_forever()
    finally:
        if started is not None:
            bridge, thread, _, transport = started
            bridge.shutdown()
            bridge.server_close()
            thread.join(timeout=5)
        signal.signal(signal.SIGTERM, previous_term)

if __name__ == "__main__":
    main()
