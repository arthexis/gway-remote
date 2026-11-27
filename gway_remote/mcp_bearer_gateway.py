"""Loopback-only bearer gate for the read-only GWA MCP upstream.

Public Nginx activation and authenticated private transport are separate gates.
"""
import json
import os
import re
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .mcp_bearer import BearerVerifier
from .mcp_tool_scope import required_scope
from .activity_feed_mcp import FEED_TOOLS, FEED_NAMES, call_feed

MAX_BODY = 65536
MAX_RESPONSE = 262144
# Agent Ops read adapters may take 20 seconds; allow bounded bridge overhead.
UPSTREAM_TIMEOUT = 30
# Discovery must recover promptly when the legacy gway-001 backend is offline.
DISCOVERY_TIMEOUT = 3
FAILURE_CODES = frozenset({"upstream_unavailable", "federation_unavailable", "bridge_unavailable", "gateway_internal_error"})
ALLOWED_METHODS = frozenset({"server/discover", "initialize", "notifications/initialized", "tools/list", "tools/call"})
ALLOWED_TOOLS = frozenset({"mcp_source_status",
    "node_list", "node_capabilities", "node_file_download", "node_exec_preview",
    "node_exec", "node_result", "node_cancel", "node_deploy", "node_deploy_status",
    "node_deploy_preview", "node_deploy_discovery", "workspace_inspect", "mcp_catalog_inspect", "node_exec_diagnostic"})

EXEC_TOOL_NAMES = frozenset({"node_exec", "node_result", "node_cancel", "node_deploy", "node_deploy_status", "node_exec_diagnostic"})
from .watchtower_exec_failure_receipts import FailureReceipts, ExecutionStageError
_EXEC_FAILURES = FailureReceipts()
EXEC_SECURITY = {"securitySchemes": [{"type": "oauth2", "scopes": ["gway:execute"]}]}
READ_SECURITY = {"securitySchemes": [{"type": "oauth2", "scopes": ["gway:read"]}]}

EXEC_TOOLS = (
    {"name": "node_exec_diagnostic", "_meta": EXEC_SECURITY,
     "description": "Read a short-lived sanitized receipt for your own execution request; never executes.",
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {
         "request_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
         "required": ["request_id"], "additionalProperties": False}},
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
    {"name": "node_deploy_discovery", "_meta": READ_SECURITY,
     "description": "Inspect live node-owned deployment declarations; no execution or paths.",
     "inputSchema": {"type": "object", "properties": {"node": {"type": "string"}},
                     "required": ["node"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "node_file_download", "_meta": READ_SECURITY,
     "description": "Read one 8 KiB Base64 chunk of a file up to 1 MiB from the operator-provisioned node export directory. Reassemble chunks using next_offset and verify sha256.",
     "inputSchema": {"type": "object", "properties": {
         "node": {"type": "string"},
         "filename": {"type": "string", "minLength": 1, "maxLength": 255},
         "offset": {"type": "integer", "minimum": 0, "maximum": 1048576}},
         "required": ["node", "filename", "offset"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
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
    if method == "node_deploy_discovery" and type(arguments) is dict and set(arguments) == {"node"}:
        if execution is None:
            raise PermissionError("deployment unavailable")
        return execution.deployment_discovery(**arguments)
    if method == "node_deploy_preview" and type(arguments) is dict and \
            {"node", "application"} <= set(arguments) and \
            set(arguments) <= {"node", "application", "revision"}:
        if execution is None:
            raise PermissionError("deployment unavailable")
        return execution.deployment_preview(**arguments)
    if method == "node_list" and arguments == {}:
        from .execution_health import project_health
        from .mcp_monitor_projection import add_monitor_status
        return add_monitor_status(project_health(node_registry_inventory.public_nodes(execution_enabled=execution is not None), execution))
    if method == "node_capabilities" and type(arguments) is dict and set(arguments) == {"node"}:
        from .execution_health import project_health
        return project_health(node_registry_inventory.capabilities(arguments["node"], execution_enabled=execution is not None), execution)
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
        route = routes[name]
        if len(route) > 6 and route[6] == "alias":
            continue
        candidates = route[5].values() if len(route) > 5 else (route,)
        for candidate in candidates:
            node, source, _, scope = candidate[:4]
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


def _project_catalog(catalog, routes):
    """One classification/projection for actual tools/list and inspect output."""
    rows = []
    for tool in catalog:
        name = tool["name"]
        route = routes.get(name)
        # Watchtower-local execute tools keep their fixed OAuth requirement,
        # including the read-like diagnostic. Dynamic providers are classified
        # using the *authenticated* route, never a caller-provided scope.
        scope = route[3] if route else ("execute" if name in EXEC_TOOL_NAMES or name == "feed__publish" else
                required_scope(tool) if trusted_source_tool(tool) else "read")
        row = {"name": name, "origin": "federated" if route else "builtin",
                     "node": route[0] if route else None,
                     "source": route[1] if route else None,
                     "classification": scope,
                     "required_scope": "gway:execute" if scope == "execute" else "gway:read"}
        if route and len(route) > 5:
            row["nodes"] = sorted(route[5])
            row["node"] = row["nodes"][0] if len(row["nodes"]) == 1 else None
            row["legacy_alias"] = len(route) > 6 and route[6] == "alias"
        rows.append(row)
    return {"schema": 1, "discovery": "node_federation", "tools": rows,
            "count": len(rows)}


def inspect_federated_catalog(federation, *, builtins=()):
    """Backward-compatible pure projection of an independently discovered catalog."""
    return _project_catalog(*federation.discover(builtins=builtins))


def effective_catalog(upstream_tools, *, federation=None, execution=None, activity_feed=None):
    """Construct the *same* effective list for tools/list and mcp_catalog_inspect.

    No additional tool registrations, approvals, transports or lookups. The
    node's authenticated federation owns each dynamic tool and its scope.
    """
    if type(upstream_tools) is not list:
        raise ValueError("invalid backend catalog")
    local_names = {tool["name"] for tool in NODE_TOOLS + EXEC_TOOLS} | FEED_NAMES
    if any(type(tool) is not dict or type(tool.get("name")) is not str
           or tool["name"] in local_names for tool in upstream_tools):
        raise ValueError("invalid or shadowed backend tool")
    names = [tool["name"] for tool in upstream_tools]
    if len(names) != len(set(names)):
        raise ValueError("duplicate backend tools")
    private_tools = [tool for tool in upstream_tools if tool["name"] in ALLOWED_TOOLS]
    if federation is not None:
        selected, routes = federation.discover(
            builtins=private_tools + list(NODE_TOOLS) + list(EXEC_TOOLS) + list(FEED_TOOLS))
        # These local declarations are appended in their original order below.
        tools = [tool for tool in selected if tool["name"] not in local_names]
    else:
        tools, routes = private_tools, {}
    tools = tools + list(NODE_TOOLS) + (list(EXEC_TOOLS) if execution is not None else [])
    if activity_feed is not None:
        tools += list(FEED_TOOLS)
    projection = _project_catalog(tools, routes)
    scoped = [scoped_tool(tool, EXEC_SECURITY if row["required_scope"] == "gway:execute"
                          else READ_SECURITY)
              for tool, row in zip(tools, projection["tools"])]
    return scoped, projection


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

    def _audit_rejection(self, status, reason):
        # Never trust inbound correlation IDs or record raw request values.
        allowed = frozenset(("origin_header","lcd_event_rejected","rpc_policy","feed_unavailable","execution_unavailable_or_invalid","legacy_tool_unregistered","federation_disabled","federated_route_missing","federated_call_rejected","insufficient_scope","authentication_required","federated_permission_denied","federated_transport_failure","federated_invalid_request","unspecified"))
        if reason not in allowed:
            reason = "unspecified"
        route = "mcp" if self.path == "/mcp" else (
            "lcd_event" if self.path == "/v1/lcd-sound/event" else "other")
        request_id = secrets.token_hex(16)
        print("gway_mcp_rejection " + json.dumps({
            "request_id": request_id, "http_status": status,
            "route": route, "origin": "watchtower_gateway",
            "reason_code": reason,
        }, separators=(",", ":")), file=sys.stderr, flush=True)
        return request_id

    def reject(self, status, *, scope=None, failure_code=None, reason=None):
        # Do not reflect exception text, RPC arguments, bearer tokens or host
        # paths. A server-generated incident ID correlates the HTTP failure
        # with a private systemd journal entry.
        diagnostic = status == 502
        if diagnostic:
            code = failure_code if failure_code in FAILURE_CODES else "gateway_internal_error"
            incident_id = secrets.token_hex(12)
            body = json.dumps({"error": {"code": code, "incident_id": incident_id}},
                              separators=(",", ":")).encode("ascii")
            print(f"gway_mcp_failure code={code} incident_id={incident_id}",
                  file=sys.stderr, flush=True)
        else:
            body = b""
        rejection_id = None
        if status in (401, 403):
            rejection_id = self._audit_rejection(
                status, reason or ("insufficient_scope" if scope == "gway:execute"
                                   else "authentication_required" if status == 401
                                   else "unspecified"))
        self.send_response(status)
        if rejection_id:
            self.send_header("X-Gway-Request-ID", rejection_id)
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
        if diagnostic:
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Gway-Failure-Code", code)
            self.send_header("X-Gway-Incident-ID", incident_id)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if diagnostic:
            self.wfile.write(body)

    def do_GET(self):
        from .mobile_feed_read import is_mobile_feed_path, handle_mobile_feed
        if is_mobile_feed_path(self.path):
            return handle_mobile_feed(self)
        if getattr(self.server, "activity_feed", None) is not None:
            from .activity_feed_http import is_feed_path, handle
            if is_feed_path(self.path):
                return handle(self, "GET")
        self.reject(405)

    def _lcd_sound_post(self):
        """Opt-in narrow event endpoint; disabled on all existing services."""
        if self.headers.get("Origin") is not None:
            return self.reject(403, reason="origin_header")
        if (self.headers.get("Transfer-Encoding") is not None
                or len(self.headers.get_all("Authorization", [])) != 1
                or len(self.headers.get_all("Content-Length", [])) != 1
                or len(self.headers.get_all("Content-Type", [])) != 1
                or self.headers.get("Content-Type", "").lower().strip() != "application/json"):
            return self.reject(400)
        supplied = self.headers.get("Authorization", "")
        if not supplied.startswith("Bearer "):
            return self.reject(401)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reject(413)
        if not 0 < length <= 8192:
            return self.reject(413)
        raw = self.rfile.read(length)
        try:
            event = json.loads(raw)
            from .lcd_sound_ingress import forward_verified_bearer
            result = forward_verified_bearer(
                event, bearer=supplied[7:], verifier=self.server.registry,
                dispatch=self.server.lcd_sound_dispatch,
                load_grants=self.server.lcd_sound_grants_loader)
            if result["status"] == "uncertain":
                code = 202
            elif result["status"] == "failed":
                code = 502
            else:
                code = 200
            body = json.dumps(result, separators=(",", ":")).encode("utf-8")
            if len(body) > 8192:
                return self.reject(502)
        except (PermissionError, ValueError, TypeError, KeyError, OSError,
                RuntimeError, UnicodeError):
            return self.reject(403, reason="lcd_event_rejected")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if getattr(self.server, "activity_feed", None) is not None:
            from .activity_feed_http import is_feed_path, handle
            if is_feed_path(self.path):
                return handle(self, "POST")
        if (self.path == "/v1/lcd-sound/event"
                and getattr(self.server, "lcd_sound_ingress_enabled", False)):
            return self._lcd_sound_post()
        if self.path != "/mcp":
            return self.reject(404)
        if self.headers.get("Origin") is not None:
            return self.reject(403, reason="origin_header")
        if len(self.headers.get_all("Authorization", [])) != 1:
            return self.reject(401)
        supplied = self.headers.get("Authorization", "")
        if not supplied.startswith("Bearer "):
            return self.reject(401)
        token = supplied[7:]
        has_read = self.server.registry.verify(token)
        has_exec = self.server.registry.verify(token, required_scope="gway:execute")
        if not (has_read or has_exec):
            if (getattr(self.server,'health_probe_enabled',False) is True
                    and self.server.registry.verify(token,required_scope='gway:health-probe')):
                return self._process_authenticated(token,False,False,probe=True)
            return self.reject(401)
        # Node audiences are resolved after validating each tool call, not
        # fixed to gway-001 for the lifetime of an entire HTTP request.
        return self._process_authenticated(token, has_read, has_exec)

    def _bridge_node_tool(self, name, arguments, token):
        from .mcp_bridge_gateway_dispatch import dispatch_node_tool, OPERATIONS
        if self.server.bridge_sessions is None or self.server.bridge_transport is None:
            raise PermissionError("bridge session missing")
        operation, scope = OPERATIONS[name]
        if not self.server.registry.verify(token, required_scope=scope):
            raise PermissionError("insufficient bridge scope")
        if scope == "gway:execute":
            principal = self.server.registry.execution_principal(token)
        else:
            principal = self.server.bridge_sessions.read_principal(token)
        from .mcp_bridge_gateway_dispatch import resolve_bridge_audience
        from .mcp_bridge_gateway_session import gateway_bridge_session
        audience = resolve_bridge_audience(
            name, arguments, execution=self.server.execution, principal=principal)
        path, key = self.server.bridge_transport
        with gateway_bridge_session(
                self.server.bridge_sessions, bearer=token,
                audience=audience) as session_id:
            return dispatch_node_tool(
                socket_path=path, key=key, session_id=session_id,
                audience=audience, principal=principal, name=name,
                arguments=arguments)

    def _offline_backend(self, payload, version):
        """Serve only gateway-owned discovery; never cache backend-only tools."""
        method = payload["method"]
        params = payload.get("params", {})
        if method == "notifications/initialized":
            if "id" in payload or type(params) is not dict:
                return self.reject(400)
            self.send_response(202)
            self.send_header("MCP-Protocol-Version", version)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "initialize":
            requested = params.get("protocolVersion", "2025-03-26") if type(params) is dict else None
            if type(requested) is not str or not requested:
                return self.reject(400)
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "gway-agent-ops", "version": "0.1.0"}}
        elif method == "tools/list":
            allowed = {"_meta"} if version == "2026-07-28" else set()
            if type(params) is not dict or set(params) - allowed:
                return self.reject(400)
            try:
                tools, _ = effective_catalog(
                    [], federation=self.server.federation,
                    execution=self.server.execution, activity_feed=getattr(self.server, 'activity_feed', None))
            except (OSError, ValueError, RuntimeError, PermissionError, TypeError, KeyError):
                return self.reject(502, failure_code="federation_unavailable")
            result = {"tools": tools}
        else:
            return self.reject(502)
        if version == "2026-07-28":
            result = {"resultType": "complete", **result}
        body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"),
                           "result": result}, separators=(",", ":")).encode()
        if len(body) > MAX_RESPONSE:
            return self.reject(502)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("MCP-Protocol-Version", version)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _process_authenticated(self, token, has_read, has_exec, *, probe=False):
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
        if probe:
            if self.headers.get('MCP-Protocol-Version','2025-03-26')!='2025-03-26':
                return self.reject(400)
            from .mcp_health_probe_ingress import rpc
            try:
                response=rpc(self.server,token,json.loads(raw))
            except (PermissionError,ValueError,RuntimeError,OSError,TypeError,KeyError):
                return self.reject(403)
            body=b'' if response is None else json.dumps(response,separators=(',',':')).encode()
            if len(body)>8192:
                return self.reject(502)
            self.send_response(202 if response is None else 200)
            if response is not None:
                self.send_header('Content-Type','application/json')
            self.send_header('MCP-Protocol-Version','2025-03-26')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            if body:self.wfile.write(body)
            return
        if not inspect_rpc(raw, self.server.approved_sources):
            return self.reject(403, reason="rpc_policy")
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
        if payload["method"] == "tools/call" and payload.get("params", {}).get("name") in FEED_NAMES:
            api = getattr(self.server, "activity_feed", None)
            if api is None:
                return self.reject(403, reason="feed_unavailable")
            name = payload["params"]["name"]
            if name == "feed__publish" and not has_exec:
                return self.reject(401, scope="gway:execute")
            if "id" not in payload or set(payload["params"]) - {"name", "arguments", "_meta"}:
                return self.reject(400)
            result = call_feed(api, name, payload["params"].get("arguments", {}), token)
            if version == "2026-07-28":
                result = {"resultType": "complete", **result}
            body = json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result},
                              separators=(",", ":")).encode()
            if len(body) > MAX_RESPONSE:
                return self.reject(502)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("MCP-Protocol-Version", version)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
                # Read the same private backend list as tools/list, then reuse
                # the *same* trusted catalog composer and scope projection.
                probe = json.dumps({"jsonrpc": "2.0", "id": 0,
                                    "method": "tools/list", "params": {}}).encode()
                headers = {"Authorization": "Bearer " + self.server.backend_token,
                           "Content-Type": "application/json",
                           "Accept": "application/json, text/event-stream",
                           "MCP-Protocol-Version": "2025-03-26"}
                try:
                    with self.server.opener.open(Request(self.server.upstream, probe,
                                                         headers), timeout=DISCOVERY_TIMEOUT) as upstream:
                        backend_reply = upstream.read(MAX_RESPONSE + 1)
                except HTTPError:
                    raise ValueError("backend rejected catalog") from None
                except (OSError, URLError):
                    # Backend unavailable: only node-owned and gateway-owned
                    # tools are eligible, never stale backend declarations.
                    backend_tools = []
                else:
                    if len(backend_reply) > MAX_RESPONSE:
                        raise ValueError("oversized backend catalog")
                    backend_tools = json.loads(backend_reply)["result"]["tools"]
                _, selected = effective_catalog(
                    backend_tools, federation=self.server.federation,
                    execution=self.server.execution, activity_feed=getattr(self.server, 'activity_feed', None))
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
                rejection_id = self._audit_rejection(200, "insufficient_scope")
                self.send_response(200)
                self.send_header("X-Gway-Request-ID", rejection_id)
                self.send_header("Content-Type", "application/json")
                self.send_header("MCP-Protocol-Version", version)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.server.execution is None or type(args) is not dict:
                return self.reject(403, reason="execution_unavailable_or_invalid")
            name = params["name"]
            try:
                principal = self.server.registry.execution_principal(token)
                if name == "node_exec_diagnostic":
                    if set(args) != {"request_id"}:
                        raise ValueError("invalid diagnostic arguments")
                    selected = _EXEC_FAILURES.inspect(args["request_id"], principal)
                elif self.server.bridge_transport is not None:
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
                if (name == "node_exec" and type(selected) is dict
                        and type(args) is dict
                        and selected.get("request_id") == args.get("request_id")
                        and selected.get("node") == args.get("node")
                        and selected.get("status") == "uncertain"
                        and selected.get("failure_stage") in (
                            "ssh_transport", "worker_readiness")):
                    _EXEC_FAILURES.record(args["request_id"], principal,
                                          selected["failure_stage"], "failure")
                    selected = {key: value for key, value in selected.items()
                                if key != "failure_stage"}
                result = {"content":[{"type":"text","text":json.dumps(selected,separators=(",",":"))}]}
            except (PermissionError, ValueError, RuntimeError, OSError, TypeError, KeyError) as exc:
                if name == "node_exec" and type(args) is dict:
                    # Only typed errors from the origin prove a failure stage.
                    # A bridge exception is opaque: never claim SSH/worker failure.
                    if isinstance(exc, ExecutionStageError):
                        _EXEC_FAILURES.record(args.get("request_id"), principal,
                                              exc.stage, "failure")
                from .mcp_bridge_transport import BridgeReadUnavailable
                code = str(exc)
                if (name in {"node_deploy", "node_deploy_status"} and
                        code in BridgeReadUnavailable.CODES and code.startswith("deployment_")):
                    result = {"content": [{"type": "text", "text": json.dumps({
                        "error": "Deployment request rejected", "code": code})}], "isError": True}
                else:
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
        if payload["method"] == "tools/call" and payload.get("params", {}).get("name") in {"node_list", "node_capabilities", "node_file_download", "node_exec_preview", "node_deploy_preview", "node_deploy_discovery", "workspace_inspect"}:
            # The enrollment ledger lives on Watchtower. Never pass these tools
            # to gway-001, and never grant the gateway access to the root DB.
            arguments = payload["params"].get("arguments", {})
            try:
                if self.server.bridge_transport is not None:
                    selected = self._bridge_node_tool(
                        payload["params"]["name"], arguments, token)
                elif payload["params"]["name"] == "workspace_inspect":
                    # Only the separate authenticated node read bridge may inspect.
                    # Never impersonate a node through Watchtower-local env/config.
                    raise PermissionError("attested read bridge unavailable")
                else:
                    # The installed Watchtower may use its existing authenticated
                    # local execution service instead of the optional signed bridge.
                    # Preserve only the same fixed deployment diagnostic codes.
                    try:
                        selected = local_node_result(payload["params"]["name"], arguments, execution=self.server.execution)
                    except (PermissionError, ValueError) as exc:
                        from .mcp_bridge_transport import BridgeReadUnavailable
                        if (payload["params"]["name"] in {"node_deploy_preview", "node_deploy_discovery"}
                                and str(exc) in BridgeReadUnavailable.CODES and str(exc).startswith("deployment_")):
                            raise BridgeReadUnavailable(str(exc)) from None
                        raise
                result = {"content": [{"type": "text", "text": json.dumps(selected, separators=(",", ":"))}]}
            except (OSError, ValueError, PermissionError, KeyError, TypeError, json.JSONDecodeError) as exc:
                # Do not return exception messages: they can contain paths or credentials.
                # WorkspaceUnavailable is a trusted local error with a fixed code.
                from .mcp_workspace_inspect import WorkspaceUnavailable
                from .mcp_bridge_transport import BridgeReadUnavailable
                code = (exc.code if isinstance(exc, (WorkspaceUnavailable, BridgeReadUnavailable))
                        else "deployment_preview_unavailable" if payload["params"]["name"] == "node_deploy_preview"
                        else "deployment_node_protocol_unavailable" if payload["params"]["name"] == "node_deploy_discovery"
                        else "workspace_inspection_unavailable" if payload["params"]["name"] == "workspace_inspect"
                        else "node_inventory_unavailable")
                result = {"content": [{"type": "text", "text": json.dumps({
                    "error": "Node inventory or deployment preview unavailable",
                    "code": code}, separators=(",", ":"))}], "isError": True}
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
                    return self.reject(403, reason="legacy_tool_unregistered")
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
                return self.reject(403, reason="federation_disabled")
            try:
                name = payload["params"]["name"]
                arguments = payload["params"].get("arguments", {})
                if type(arguments) is not dict:
                    return self.reject(400)
                _, routes = self.server.federation.discover()
                if name not in routes:
                    return self.reject(403, reason="federated_route_missing")
                if routes[name][3] == "execute" and not has_exec:
                    return self.reject(401, scope="gway:execute")
                # Reuse the same authenticated route snapshot used for
                # OAuth admission. A second discovery would introduce a
                # transient availability/classification race inside one call.
                from .mcp_principal_admission import owner_bound, verify_admission
                scope = "execute" if has_exec else "read"
                options = {}
                if owner_bound(routes[name][1]):
                    options["verified_principal"] = verify_admission(
                        self.server.registry, token, scope)
                from .agentops_invocation_trace import ingress
                with ingress(routes[name][1], registry=self.server.registry,
                             credential=token, scope=scope, rpc_id=payload.get("id")):
                    selected = self.server.federation.call(
                        name, arguments, authorized_scope=scope,
                        routes=routes, **options)
                from .mcp_gateway_federation import federated_tool_result
                result = federated_tool_result(selected)
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
            except PermissionError:
                return self.reject(403, reason="federated_permission_denied")
            except (RuntimeError, OSError):
                return self.reject(403, reason="federated_transport_failure")
            except (ValueError, TypeError, KeyError):
                return self.reject(403, reason="federated_invalid_request")
        # Forward only to a fixed private endpoint; never forward client headers.
        headers = {"Authorization": "Bearer " + self.server.backend_token,
                   "X-Gway-Caller-Scope": "execute" if has_exec else "read",
                   "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-03-26"}
        req = Request(self.server.upstream, raw, headers, method="POST")
        try:
            timeout = DISCOVERY_TIMEOUT if payload["method"] in {
                "initialize", "tools/list", "notifications/initialized"} else UPSTREAM_TIMEOUT
            with self.server.opener.open(req, timeout=timeout) as response:
                status = response.status
                body = response.read(MAX_RESPONSE + 1)
                typ = response.headers.get("Content-Type", "application/json")
        except HTTPError as exc:
            status, body, typ = exc.code, b"", "application/json"
            exc.close()
        except (OSError, URLError):
            if payload["method"] in {"initialize", "tools/list", "notifications/initialized"}:
                return self._offline_backend(payload, version)
            return self.reject(502, failure_code="upstream_unavailable")
        except ValueError:
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
                result["tools"], _ = effective_catalog(
                    result["tools"], federation=self.server.federation,
                    execution=self.server.execution, activity_feed=getattr(self.server, "activity_feed", None))
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

def make_server(address, registry, upstream, backend_token, *, execution=None, bridge_sessions=None, bridge_transport=None, approved_sources=None, federation=None, lcd_sound_ingress_enabled=False, lcd_sound_dispatch=None, lcd_sound_grants_loader=None, activity_feed=None, health_probe_enabled=False):
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
    if type(lcd_sound_ingress_enabled) is not bool:
        raise ValueError("invalid LCD/Sound ingress activation")
    if type(health_probe_enabled) is not bool:
        raise ValueError('invalid probe activation')
    server.health_probe_enabled=health_probe_enabled
    server.activity_feed = activity_feed
    server.lcd_sound_ingress_enabled = lcd_sound_ingress_enabled
    server.lcd_sound_dispatch = lcd_sound_dispatch
    server.lcd_sound_grants_loader = lcd_sound_grants_loader
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
    routing_mode = os.environ.get("GWAY_MCP_NODE_ROUTING", "legacy")
    if routing_mode not in ("legacy", "canonical-with-aliases", "canonical"):
        raise ValueError("invalid MCP node routing mode")
    if execution is not None:
        from .mcp_gateway_federation import FederatedProviders
        from .mcp_provider_transport import ProviderTransport
        transport = execution.relay.transport
        federation = FederatedProviders(
            transport=ProviderTransport(transport),
            nodes=lambda: tuple(transport.transports) if hasattr(transport, "transports")
            else (transport.node.node,),
            canonical=routing_mode != "legacy",
            legacy_aliases=routing_mode != "canonical")
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
    # Intentional opt-in: production service files do not set this switch.
    # Require the existing execute transport and an already published,
    # root-owned source grant before opening the extra loopback-only route.
    ingress_switch = os.environ.get("GWAY_LCD_SOUND_INGRESS_ENABLED", "0")
    if ingress_switch not in ("0", "1"):
        raise ValueError("invalid LCD/Sound ingress activation flag")
    ingress_enabled = ingress_switch == "1"
    if ingress_enabled:
        if execution is None:
            raise PermissionError("LCD/Sound ingress needs pinned execution relay")
        from .lcd_sound_grant_store import load_operator_grants
        load_operator_grants()  # fail at startup for missing/unsafe grants
    verifier = BearerVerifier(args.database)
    feed_switch = os.environ.get("GWAY_ACTIVITY_FEED_ENABLED", "0")
    if feed_switch not in ("0", "1"):
        raise ValueError("invalid Activity Feed activation flag")
    activity_feed = None
    if feed_switch == "1":
        from .activity_feed_http import ActivityFeedAPI, load_feed_grants
        from .activity_feed import ActivityFeedStore
        from pathlib import Path
        feed_path = Path(os.environ.get("GWAY_ACTIVITY_FEED_DATABASE", ""))
        if (not feed_path.is_absolute() or ".." in feed_path.parts
                or feed_path.resolve() == Path(args.database).resolve()):
            raise ValueError("dedicated absolute Activity Feed database required")
        if os.environ.get("GWAY_ACTIVITY_FEED_REQUIRE_VOLUME") == "1":
            from .activity_feed_maintenance import check_volume
            from . import activity_feed_local
            try:
                check_volume(feed_path.parent, "central")
                load_feed_grants()
                store = ActivityFeedStore(feed_path)
                activity_feed_local.ready(store)
                activity_feed_local.bind(store)
                activity_feed = ActivityFeedAPI(store, verifier, load_feed_grants)
            except (OSError, ValueError, RuntimeError, __import__("sqlite3").Error):
                print("activity_feed_unavailable", file=sys.stderr, flush=True)
                # A missing mount or unsafe grant must never disable existing MCP.
                activity_feed = None
        else:
            load_feed_grants()  # fail closed before creating storage
            activity_feed = ActivityFeedAPI(ActivityFeedStore(feed_path), verifier, load_feed_grants)
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
                         federation=federation,
                         lcd_sound_ingress_enabled=ingress_enabled, activity_feed=activity_feed,
                         health_probe_enabled=os.environ.get("GWAY_MCP_HEALTH_PROBE_ENABLED")=="1", **options) as service:
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
