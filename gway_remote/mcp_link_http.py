"""Separate loopback-only OAuth browser linking HTTP adapter.

Runs under token-admin identity, never under the MCP gateway verifier identity.
Requires an exact registered ChatGPT callback URL set by the operator.
"""
import json
import os
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .mcp_bearer import BearerRegistry
from .mcp_link import LinkFlow, RESOURCE

ISSUER = "https://remote.arthexis.com"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, body=b"", typ="text/plain; charset=utf-8", headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def get_cookie(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get("gwa_link")
        return "" if morsel is None else morsel.value

    def form(self):
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return {}
        if not 0 < size <= 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
            return {}
        try:
            return {k: v[0] for k, v in parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True).items()}
        except (ValueError, UnicodeError):
            return {}

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == "/.well-known/oauth-authorization-server":
            data = {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/oauth/authorize",
                    "token_endpoint": ISSUER + "/oauth/token", "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "scopes_supported": ["gway:read"],
                    "authorization_response_iss_parameter_supported": True}
            return self.respond(200, json.dumps(data), "application/json")
        if path.path == "/.well-known/oauth-protected-resource/mcp":
            return self.respond(200, json.dumps({"resource": RESOURCE,
                   "authorization_servers": [ISSUER], "scopes_supported": ["gway:read"]}), "application/json")
        if path.path != "/oauth/authorize":
            return self.respond(404)
        params = parse_qs(path.query, keep_blank_values=True)
        if any(len(v) != 1 for v in params.values()):
            return self.respond(400)
        try:
            session, page = self.server.link.begin(**{k: v[0] for k, v in params.items()})
        except (TypeError, ValueError):
            return self.respond(400)
        return self.respond(200, page, "text/html; charset=utf-8",
                            [("Set-Cookie", "gwa_link=" + session + "; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=300")])

    def do_POST(self):
        params = self.form()
        if self.path == "/connect":
            try:
                dest = self.server.link.connect(self.get_cookie(), params.get("csrf"), params.get("bearer"))
            except (ValueError, TypeError):
                return self.respond(403)
            return self.respond(303, headers=[("Location", dest),
                ("Set-Cookie", "gwa_link=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0")])
        if self.path != "/oauth/token":
            return self.respond(404)
        try:
            payload = self.server.link.redeem(**params)
        except (TypeError, ValueError):
            return self.respond(400, '{"error":"invalid_grant"}', "application/json")
        return self.respond(200, json.dumps(payload), "application/json")

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--database", required=True)
    p.add_argument("--port", type=int, default=19012)
    a = p.parse_args()
    client = os.environ.get("GWAY_MCP_OAUTH_CLIENT_ID", "")
    redirect = os.environ.get("GWAY_MCP_OAUTH_REDIRECT_URI", "")
    flow = LinkFlow(BearerRegistry(a.database), client_id=client, redirect_uri=redirect)
    with ThreadingHTTPServer(("127.0.0.1", a.port), Handler) as server:
        server.link = flow
        server.serve_forever()

if __name__ == "__main__":
    main()
