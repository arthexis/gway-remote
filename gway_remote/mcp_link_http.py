"""Separate loopback-only OAuth browser linking HTTP adapter.

Runs under token-admin identity, never under the MCP gateway verifier identity.
Requires an exact registered ChatGPT callback URL set by the operator.
"""
import json
from html import escape
import os
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .mcp_bearer import BearerRegistry
from .mcp_link import LinkFlow, RESOURCE, ISSUER, OAUTH_PAGE_STYLE, _connect_error


AUTHORIZE_FIELDS = frozenset({"client_id", "redirect_uri", "resource", "response_type",
                             "code_challenge", "code_challenge_method", "state", "scope"})
TOKEN_FIELDS = frozenset({"client_id", "code", "redirect_uri", "code_verifier", "grant_type", "resource"})
REASONS = frozenset({"page", "code", "issued", "discovery", "malformed", "missing_parameter",
                     "invalid_client", "invalid_request", "invalid_scope_or_pkce", "invalid_pkce",
                     "invalid_state", "link_capacity_reached", "expired_session", "session_unavailable", "csrf_denied",
                     "invalid_bearer", "scope_selection_denied", "invalid_parent_credential", "invalid_grant", "unsupported_auth"})


class OAuthAudit:
    """Fixed-schema diagnostics: no request text, at most 61 records per minute."""
    def __init__(self):
        self.lock = threading.Lock()
        self.window = 0
        self.count = 0

    def emit(self, phase, reason, status, comparisons=None):
        if (os.environ.get("GWAY_MCP_OAUTH_DIAGNOSTICS") == "0" or
                phase not in {"authorize", "connect", "token", "metadata"} or
                reason not in REASONS or status not in {200, 303, 400, 403}):
            return
        with self.lock:
            now = int(time.monotonic() // 60)
            if now != self.window:
                self.window, self.count = now, 0
            self.count += 1
            if self.count > 61:
                return
            if self.count == 61:
                record = {"event": "oauth_link", "phase": "diagnostics", "reason": "rate_limited", "status": 0}
            else:
                record = {"event": "oauth_link", "phase": phase, "reason": reason, "status": status}
                if comparisons is not None:
                    for key in ("client_match", "redirect_match", "resource_match", "scope_read", "pkce_s256", "grant_code"):
                        if type(comparisons.get(key)) is bool:
                            record[key] = comparisons[key]
            try:
                sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
                sys.stderr.flush()
            except (OSError, ValueError):
                # Diagnostics must not prevent an otherwise valid OAuth flow.
                pass


AUDIT = OAuthAudit()


def oauth_values(values, fields):
    # RFC 6749 sections 3.1/3.2: unknown parameters are ignored and empty
    # parameters are treated as omitted. Duplicate occurrences are rejected
    # before this normalization, including unknown/empty parameters.
    return {key: value for key, value in values.items() if key in fields and value != ""}


def failure_reason(exc):
    if isinstance(exc, TypeError):
        return "missing_parameter"
    return str(exc) if str(exc) in REASONS else "invalid_request"


def callback_handoff(destination, registered_callback):
    """Top-level navigation, not a cross-origin redirect of a submitted form.

    Chromium may block form submission redirect chains under form-action CSP.
    A zero-delay meta refresh plus a plain link works without JavaScript; the
    fallback remains accessible if automatic navigation is restricted.
    Only the already validated, pre-registered OAuth callback is permitted.
    """
    parsed = urlsplit(destination)
    configured = urlsplit(registered_callback)
    delimiter = "&" if configured.query else "?"
    if (parsed.scheme != "https" or parsed.netloc != configured.netloc
            or parsed.path != configured.path
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment or not destination.startswith(registered_callback + delimiter)):
        raise ValueError("unsafe_callback_handoff")
    url = escape(destination, quote=True)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='refresh' content='0;url=" + url + "'>"
            "<title>Returning to ChatGPT</title>"
            + OAUTH_PAGE_STYLE + "</head><body>"
            "<main><h1>Connected to GWA Remote</h1>"
            "<p>Authorization accepted. Returning to ChatGPT...</p>"
            "<p>If you are not redirected automatically, "
            "<a rel='noreferrer' href='" + url + "'>Continue to ChatGPT</a>.</p>"
            "</main></body></html>")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def audit(self, phase, reason, status, values=None):
        comparisons = None
        if values is not None:
            flow = self.server.link
            comparisons = {"client_match": values.get("client_id") == flow.client_id,
                           "redirect_match": values.get("redirect_uri") == flow.redirect_uri,
                           "resource_match": values.get("resource") == flow.resource,
                           "scope_read": values.get("scope") == "gway:read",
                           "pkce_s256": values.get("code_challenge_method") == "S256",
                           "grant_code": values.get("grant_type") == "authorization_code"}
        AUDIT.emit(phase, reason, status, comparisons)

    def respond(self, status, body=b"", typ="text/plain; charset=utf-8", headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # Chromium applies form-action to the post-submission callback redirect.
        # Only the protected, registered callback origin may leave this site.
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; "
                         "form-action 'self' " + self.server.link.callback_origin + "; base-uri 'none'")
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
        if (self.headers.get("Transfer-Encoding") is not None
                or any(len(self.headers.get_all(name, [])) != 1 for name in ("Content-Length", "Content-Type"))
                or len(self.headers.get_all("Cookie", [])) > 1):
            return None
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if not 0 < size <= 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
            return None
        try:
            values = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True, max_num_fields=64)
            if any(len(v) != 1 for v in values.values()):
                return None
            return {k: v[0] for k, v in values.items()}
        except (ValueError, UnicodeError):
            return None

    def do_GET(self):
        if len(self.headers.get_all("Cookie", [])) > 1:
            return self.respond(400)
        path = urlsplit(self.path)
        if path.path == "/.well-known/oauth-authorization-server":
            data = {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/oauth/authorize",
                    "token_endpoint": ISSUER + "/oauth/token", "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "scopes_supported": ["gway:read", "gway:execute"],
                    "authorization_response_iss_parameter_supported": True}
            self.audit("metadata", "discovery", 200)
            return self.respond(200, json.dumps(data), "application/json")
        if path.path == "/.well-known/oauth-protected-resource/mcp":
            self.audit("metadata", "discovery", 200)
            return self.respond(200, json.dumps({"resource": RESOURCE,
                   "authorization_servers": [ISSUER], "scopes_supported": ["gway:read", "gway:execute"]}), "application/json")
        if path.path != "/oauth/authorize":
            return self.respond(404)
        try:
            if len(path.query) > 8192:
                raise ValueError("query_too_large")
            params = parse_qs(path.query, keep_blank_values=True, max_num_fields=64)
            if any(len(v) != 1 for v in params.values()):
                raise ValueError("duplicate_parameter")
        except ValueError:
            self.audit("authorize", "malformed", 400)
            return self.respond(400)
        values = oauth_values({k: v[0] for k, v in params.items()}, AUTHORIZE_FIELDS)
        # Omitted scope: allow explicit choice on the form, defaulting to read.
        # Client-requested scope remains fixed and cannot be escalated.
        try:
            session, page = self.server.link.begin(**values)
        except (TypeError, ValueError) as exc:
            # Invalid clients and callback URIs must never be redirected.
            # Valid registered clients receive RFC 9207 issuer identification
            # on OAuth errors, not just on successful authorization codes.
            reason = failure_reason(exc)
            error = ("invalid_scope" if reason == "invalid_scope_or_pkce"
                     else "invalid_request")
            destination = self.server.link.authorization_error_redirect(
                client_id=values.get("client_id"),
                redirect_uri=values.get("redirect_uri"),
                state=values.get("state"), error=error)
            if destination is None:
                self.audit("authorize", reason, 400, values)
                return self.respond(400)
            self.audit("authorize", reason, 303, values)
            return self.respond(303, headers=[("Location", destination)])
        self.audit("authorize", "page", 200, values)
        return self.respond(200, page, "text/html; charset=utf-8",
                            [("Set-Cookie", "gwa_link=" + session + "; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=300")])

    def do_POST(self):
        params = self.form()
        if params is None:
            if self.path in ("/connect", "/oauth/token"):
                self.audit("connect" if self.path == "/connect" else "token", "malformed", 400)
            return self.respond(400)
        if self.path == "/connect":
            try:
                dest = self.server.link.connect(self.get_cookie(), params.get("csrf"), params.get("bearer"),
                                                selected_scope=params.get("scope"))
            except (ValueError, TypeError) as exc:
                reason = failure_reason(exc)
                self.audit("connect", reason, 403)
                if reason in ("expired_session", "session_unavailable"):
                    return self.respond(403, "This sign-in form expired or was already submitted. "
                                        "Return to ChatGPT and start Connect again.")
                # Do not reveal bearer validity; show scope guidance only.
                return self.respond(403, _connect_error("gway:read or gway:execute"),
                                    "text/html; charset=utf-8")
            # Respond with a document, not a cross-origin 303 chained to
            # the POST. Chromium may suppress the latter under form-action CSP,
            # consuming the one-shot session while leaving the form displayed.
            try:
                handoff = callback_handoff(dest, self.server.link.redirect_uri)
            except ValueError:
                self.audit("connect", "invalid_request", 403)
                return self.respond(403)
            self.audit("connect", "code", 200)
            return self.respond(200, handoff, "text/html; charset=utf-8",
                [("Set-Cookie", "gwa_link=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0")])
        if self.path != "/oauth/token":
            return self.respond(404)
        # Registered as a public PKCE client (token_endpoint_auth_method=none).
        # Ignore an empty compatibility field, but never pretend to validate
        # supplied client authentication for a client with no stored secret.
        if params.get("client_secret") or self.headers.get("Authorization") is not None:
            self.audit("token", "unsupported_auth", 400)
            return self.respond(400, '{"error":"invalid_client"}', "application/json")
        values = oauth_values(params, TOKEN_FIELDS)
        try:
            payload = self.server.link.redeem(**values)
        except (TypeError, ValueError) as exc:
            self.audit("token", failure_reason(exc), 400, values)
            return self.respond(400, '{"error":"invalid_grant"}', "application/json")
        self.audit("token", "issued", 200, values)
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
