"""Authenticated, sessionless MCP Streamable HTTP transport (read-only).

Bind only to loopback. TLS termination and operator auth upstream are required
before any remote connector is configured; this process never exposes dispatch.
"""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import mcp_agent

MAX_REQUEST = 65536
PROTOCOL = "2025-03-26"


def handle(payload):
    if type(payload) is not dict or payload.get("jsonrpc") != "2.0":
        return None, -32600, "Invalid Request"
    method = payload.get("method")
    params = payload.get("params", {})
    if method == "initialize":
        return {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                "serverInfo": {"name": "gway-agent-ops", "version": "0.1.0"}}, None, None
    if method == "tools/list":
        return {"tools": mcp_agent.list_tools()}, None, None
    if method == "tools/call":
        if type(params) is not dict or type(params.get("name")) is not str:
            return None, -32602, "Invalid params"
        try:
            result = mcp_agent.call_tool(params["name"], params.get("arguments", {}))
        except (ValueError, TypeError):
            return None, -32602, "Invalid params"
        except Exception:
            # Never return CLI output, filesystem paths, or credentials on failure.
            return {"content": [{"type": "text", "text": "Agent Ops unavailable"}],
                    "isError": True}, None, None
        return {"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}]}, None, None
    if method == "notifications/initialized":
        return None, None, None
    return None, -32601, "Method not found"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Avoid request logs containing accidental sensitive values.
        pass

    def do_GET(self):
        self.send_error(405)

    def do_POST(self):
        if self.path != "/mcp":
            self.send_error(404)
            return
        token = os.environ.get("GWAY_MCP_BEARER_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(supplied, "Bearer " + token):
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Bearer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        origin = self.headers.get("Origin")
        if origin:
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_REQUEST:
            self.send_error(413)
            return
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            self.send_error(400)
            return
        result, code, message = handle(payload)
        if result is None and code is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        response = {"jsonrpc": "2.0", "id": payload.get("id")}
        if code is not None:
            response["error"] = {"code": code, "message": message}
        else:
            response["result"] = result
        body = json.dumps(response, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("MCP-Protocol-Version", PROTOCOL)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host="127.0.0.1", port=8770):
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("mcp_must_bind_to_loopback")
    if not os.environ.get("GWAY_MCP_BEARER_TOKEN"):
        raise ValueError("mcp_bearer_token_required")
    with ThreadingHTTPServer((host, port), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    serve()
