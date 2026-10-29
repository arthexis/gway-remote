"""Loopback-only bearer gate for the read-only GWA MCP upstream.

Public Nginx activation and authenticated private transport are separate gates.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .mcp_bearer import BearerVerifier

MAX_BODY = 65536
MAX_RESPONSE = 262144
ALLOWED_METHODS = frozenset({"initialize", "notifications/initialized", "tools/list", "tools/call"})
ALLOWED_TOOLS = frozenset({"agent_list_issues", "agent_status", "agent_preview", "agent_observe",
    "github_workflow_runs", "github_workflow_status", "github_workflow_errors"})

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

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

    def reject(self, status):
        self.send_response(status)
        if status == 401:
            self.send_header("WWW-Authenticate", "Bearer")
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
        if not self.server.registry.verify(supplied[7:]):
            return self.reject(401)
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self.reject(415)
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.reject(413)
        if not 0 < length <= MAX_BODY:
            return self.reject(413)
        raw = self.rfile.read(length)
        if not inspect_rpc(raw):
            return self.reject(403)
        # Forward only to a fixed private endpoint; never forward client headers.
        headers = {"Authorization": "Bearer " + self.server.backend_token,
                   "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-03-26"}
        req = Request(self.server.upstream, raw, headers, method="POST")
        try:
            with self.server.opener.open(req, timeout=8) as response:
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
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def make_server(address, registry, upstream, backend_token):
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
    with make_server(("127.0.0.1", args.port), BearerVerifier(args.database), args.upstream, token) as service:
        service.serve_forever()

if __name__ == "__main__":
    main()
