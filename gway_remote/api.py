"""Private HTTP adapter; TLS termination belongs to the trusted gateway."""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address

from . import mobile

WIREGUARD_BIND_ADDRESS = "10.90.0.2"
MAX_BODY = 8192
MAX_RESPONSE = 1024 * 1024


def handler_for(token):
    if not isinstance(token, str) or not token:
        raise ValueError("A nonempty API token is required")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Do not log URL query parameters, authorization headers, or bodies.
            pass

        def respond(self, status, document):
            data = json.dumps(document, allow_nan=False).encode("utf-8")
            if len(data) > MAX_RESPONSE:
                status = 500
                data = b'{"error":"response_too_large"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + token
            if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
                self.respond(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if self.path not in ("/api/v1/health", "/api/v1/commands"):
                self.respond(404, {"error": "not_found"})
                return
            if not self.authorized():
                return
            if self.path == "/api/v1/health":
                self.respond(200, {"status": "ok", "api": "gway-remote/v1"})
            else:
                self.respond(200, {"commands": mobile.commands()})

        def do_POST(self):
            if self.path != "/api/v1/execute":
                self.respond(404, {"error": "not_found"})
                return
            if not self.authorized():
                return
            length = self.headers.get("Content-Length")
            if length is None or not length.isascii() or not length.isdecimal():
                self.respond(411, {"error": "content_length_required"})
                return
            if int(length) > MAX_BODY:
                self.respond(413, {"error": "request_too_large"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self.respond(415, {"error": "unsupported_media_type"})
                return
            try:
                request = json.loads(self.rfile.read(int(length)))
            except (UnicodeDecodeError, ValueError):
                self.respond(400, {"error": "invalid_json"})
                return
            if not isinstance(request, dict) or set(request) != {"command", "arguments"}:
                self.respond(400, {"error": "invalid_request"})
                return
            try:
                result = mobile.execute(request["command"], request["arguments"])
            except ValueError as exc:
                self.respond(400, {"error": str(exc)})
                return
            except Exception:
                self.respond(500, {"error": "execution_failed"})
                return
            self.respond(200, {"command": request["command"], "status": "completed", "result": result})

    return Handler


def serve(host="127.0.0.1", port=8765, token=None):
    if not (ip_address(host).is_loopback or host == WIREGUARD_BIND_ADDRESS):
        raise ValueError("API must bind to loopback or the configured WireGuard address")
    token = token if token is not None else os.environ.get("GWAY_REMOTE_API_TOKEN")
    with ThreadingHTTPServer((host, port), handler_for(token)) as server:
        server.serve_forever()
