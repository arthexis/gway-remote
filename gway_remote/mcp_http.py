"""Loopback-only, authenticated MCP Streamable HTTP transport (read-only).

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


def handle(payload):
    """Return (result, error_code, safe_error_message) for one JSON-RPC message."""
    if type(payload) is not dict or payload.get("jsonrpc") != "2.0":
        return None, -32600, "Invalid Request"
    method = payload.get("method")
    if type(method) is not str:
        return None, -32600, "Invalid Request"
    params = payload.get("params", {})
    if method == "initialize":
        if type(params) is not dict:
            return None, -32602, "Invalid params"
        requested = params.get("protocolVersion", PROTOCOL)
        if requested != PROTOCOL:
            return None, -32602, "Unsupported protocol version"
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
            result = mcp_agent.call_tool(params["name"], params.get("arguments", {}))
        except (ValueError, TypeError):
            return None, -32602, "Invalid params"
        except Exception:
            # Agent errors must not leak subprocess output or local file paths.
            return {"content": [{"type": "text", "text": "Agent Ops unavailable"}],
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
        token = os.environ.get("GWAY_MCP_BEARER_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(supplied, "Bearer " + token):
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
        if version is not None and version != PROTOCOL:
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
        result, code, message = handle(payload)
        if result is None and code is None:
            self._empty(202)
            return
        response = {"jsonrpc": "2.0", "id": payload.get("id") if type(payload) is dict else None}
        if code is not None:
            response["error"] = {"code": code, "message": message}
        else:
            response["result"] = result
        body = json.dumps(response, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("MCP-Protocol-Version", PROTOCOL)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host="127.0.0.1", port=8770):
    if host != "127.0.0.1":
        raise ValueError("mcp_must_bind_to_loopback")
    if not os.environ.get("GWAY_MCP_BEARER_TOKEN"):
        raise ValueError("mcp_bearer_token_required")
    with ThreadingHTTPServer((host, port), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    serve()
