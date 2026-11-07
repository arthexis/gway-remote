"""Loopback-only, authenticated MCP Streamable HTTP transport.

This transport supports JSON replies (no SSE streams or sessions). An HTTPS
gateway and verified client authentication remain prerequisites for external use.
"""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import mcp_agent

MAX_REQUEST = 65536
PROTOCOL = "2025-03-26"
MODERN_PROTOCOL = "2026-07-28"


def handle(payload, *, authorized_scope="read"):
    """Return (result, error_code, safe_error_message) for one JSON-RPC message."""
    if type(payload) is not dict or payload.get("jsonrpc") != "2.0":
        return None, -32600, "Invalid Request"
    method = payload.get("method")
    if type(method) is not str:
        return None, -32600, "Invalid Request"
    params = payload.get("params", {})
    if method == "server/discover":
        if type(params) is not dict:
            return None, -32602, "Invalid params"
        return {"resultType": "complete", "supportedVersions": [MODERN_PROTOCOL, PROTOCOL],
                "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo":
                          {"name": "gway-agent-ops", "version": "0.1.0"}}}, None, None
    if method == "initialize":
        if type(params) is not dict:
            return None, -32602, "Invalid params"
        requested = params.get("protocolVersion", PROTOCOL)
        if not isinstance(requested, str) or not requested:
            return None, -32602, "Invalid protocol version"
        # MCP lifecycle negotiation: offer our supported version when the
        # client requests another; the client decides whether it can use it.
        return {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                "serverInfo": {"name": "gway-agent-ops", "version": "0.1.0"}}, None, None
    if method == "notifications/initialized" and "id" not in payload:
        return None, None, None
    if "id" not in payload:
        # Ignore unknown notifications; no JSON-RPC reply is allowed.
        return None, None, None
    if method == "tools/list":
        if type(params) is not dict or params:
            return None, -32602, "Invalid params"
        return {"tools": mcp_agent.list_tools()}, None, None
    if method == "tools/call":
        if type(params) is not dict or type(params.get("name")) is not str:
            return None, -32602, "Invalid params"
        try:
            result = mcp_agent.call_tool(params["name"], params.get("arguments", {}),
                                         authorized_scope=authorized_scope)
        except (ValueError, TypeError) as exc:
            # Expose only stable, audited internal error identifiers.
            code = str(exc)
            allowed = {"mcp_tool_not_allowed", "mcp_execute_scope_required", "invalid_arguments"}
            return None, -32602, code if code in allowed else "Invalid params"
        except Exception as exc:
            # Raw provider exceptions can contain secrets, paths or response bodies.
            # Return actionable provider identity and exception class, not raw text.
            name = params["name"]
            provider = name.split("__", 1)[0] if "__" in name else "gway-remote"
            detail = {"provider": provider, "error_type": type(exc).__name__,
                      "status": "failed"}
            return {"content": [{"type": "text", "text": json.dumps(detail)}],
                    "isError": True}, None, None
        return {"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}]}, None, None
    return None, -32601, "Method not found"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress paths, credentials and caller-controlled request metadata.
        pass

    def _empty(self, status, **headers):
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _authorized(self):
        if len(self.headers.get_all("Authorization", [])) != 1:
            self._empty(401, WWW_Authenticate="Bearer")
            return False
        token = os.environ.get("GWAY_MCP_BEARER_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
            self._empty(401, WWW_Authenticate="Bearer")
            return False
        # Reject ALL browser origins by default; allow only server-to-server clients.
        if self.headers.get("Origin") is not None:
            self._empty(403)
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        if self.path != "/mcp":
            self._empty(404)
        else:
            # Stateless server does not expose SSE listeners.
            self._empty(405, Allow="POST")

    def do_POST(self):
        if not self._authorized():
            return
        if self.path != "/mcp":
            self._empty(404)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._empty(415)
            return
        accept = self.headers.get("Accept", "")
        accepted = {p.split(";", 1)[0].strip() for p in accept.split(",")}
        if not {"application/json", "text/event-stream"}.issubset(accepted):
            self._empty(406)
            return
        version = self.headers.get("MCP-Protocol-Version")
        if version is not None and version not in (PROTOCOL, MODERN_PROTOCOL):
            self._empty(400)
            return
        if (self.headers.get("Transfer-Encoding") is not None
                or len(self.headers.get_all("Content-Length", [])) != 1
                or len(self.headers.get_all("Content-Type", [])) != 1):
            self._empty(400)
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_REQUEST:
            self._empty(413)
            return
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            self._empty(400)
            return
        # This constrained transport implements single messages only.
        if type(payload) is list:
            self._empty(400)
            return
        if type(payload) is dict and version == MODERN_PROTOCOL:
            meta = payload.get("params", {}).get("_meta") if type(payload.get("params")) is dict else None
            if not isinstance(meta, dict) or meta.get("io.modelcontextprotocol/protocolVersion") != MODERN_PROTOCOL:
                self._empty(400)
                return
            if payload.get("method") in ("tools/list", "tools/call"):
                payload = {**payload, "params": {k: v for k, v in payload["params"].items() if k != "_meta"}}
        # Only the private bearer-authenticated gateway may supply this assertion.
        # Reject duplicate values to prevent header-smuggling ambiguity.
        scopes = self.headers.get_all("X-Gway-Caller-Scope", [])
        if len(scopes) > 1:
            self._empty(403)
            return
        caller_scope = scopes[0] if scopes else "read"
        if caller_scope not in ("read", "execute"):
            self._empty(403)
            return
        result, code, message = handle(payload, authorized_scope=caller_scope)
        if result is None and code is None:
            self._empty(202)
            return
        response = {"jsonrpc": "2.0", "id": payload.get("id") if type(payload) is dict else None}
        if code is not None:
            response["error"] = {"code": code, "message": message}
        else:
            if version == MODERN_PROTOCOL and isinstance(result, dict) and "resultType" not in result:
                result = {"resultType": "complete", **result}
            response["result"] = result
        body = json.dumps(response, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("MCP-Protocol-Version", version if version == MODERN_PROTOCOL else PROTOCOL)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host="127.0.0.1", port=8770):
    if host != "127.0.0.1":
        raise ValueError("mcp_must_bind_to_loopback")
    if not os.environ.get("GWAY_MCP_BEARER_TOKEN"):
        raise ValueError("mcp_bearer_token_required")
    policy_path = os.environ.get("GWAY_MCP_SOURCE_POLICY")
    policy_sha = os.environ.get("GWAY_MCP_SOURCE_POLICY_SHA256")
    if bool(policy_path) != bool(policy_sha):
        raise ValueError("incomplete source policy configuration")
    if policy_path:
        from .mcp_source_policy import load_source_policy
        registrations, approved = load_source_policy(
            policy_path, expected_sha256=policy_sha, builtins=mcp_agent.TOOLS)
        mcp_agent.configure_sources(registrations, approved)
    with ThreadingHTTPServer((host, port), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    serve()
