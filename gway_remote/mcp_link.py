"""One-time bearer-link browser flow for a pre-registered OAuth client.

Do not deploy as a public service before the OAuth transport and client
acceptance tests are completed. This component never exposes token issuance
through MCP or Agent Ops.
"""
import base64
import hashlib
from html import escape
import hmac
import secrets
import time
from urllib.parse import urlencode, urlsplit

from .mcp_bearer import BearerRegistry

RESOURCE = "https://remote.arthexis.com/mcp"


def _challenge(verifier):
    if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128:
        return None
    if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~" for c in verifier):
        return None
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _safe_redirect(value, redirect):
    parsed = urlsplit(value)
    allowed = urlsplit(redirect)
    return bool(value == redirect and parsed.scheme == "https"
                and parsed.netloc == allowed.netloc and not parsed.fragment)


def _html(form_token, error=""):
    warning = "<p role='alert'>Invalid or expired bearer token.</p>" if error else ""
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Connect GWA Remote</title>"
            "<style>body{font:1rem system-ui;background:#111827;color:#f9fafb;"
            "padding:3rem 1rem}main{max-width:30rem;margin:auto}"
            "input{box-sizing:border-box;width:100%;padding:.85rem;margin:.8rem 0;"
            "font-size:1rem;border-radius:.5rem}button{padding:.85rem 1.4rem;"
            "border:0;border-radius:.5rem;cursor:pointer}</style></head><body>"
            "<main><h1>Connect GWA Remote</h1><p>Enter the read-only bearer token "
            "generated on your Watchtower console. It is verified once and "
            "is not stored in the browser session.</p>"
            + warning + "<form method='post' action='/connect'>"
            "<input type='hidden' name='csrf' value='" + escape(form_token, quote=True) + "'>"
            "<label for='bearer'>GWA Remote bearer token</label>"
            "<input id='bearer' name='bearer' type='password' autocomplete='off' "
            "autocapitalize='off' spellcheck='false' required>"
            "<button type='submit'>Connect</button></form></main></body></html>")


class LinkFlow:
    """Ephemeral browser state; no token retained in session state."""
    def __init__(self, registry, *, client_id, redirect_uri, resource=RESOURCE):
        if not client_id or not _safe_redirect(redirect_uri, redirect_uri):
            raise ValueError("pre_registered_https_redirect_required")
        if resource != RESOURCE:
            raise ValueError("unexpected_resource")
        self.registry = registry
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.resource = resource
        self.pending = {}
        self.codes = {}

    def begin(self, *, client_id, redirect_uri, resource, response_type,
              code_challenge, code_challenge_method, state, scope):
        if client_id != self.client_id or not _safe_redirect(redirect_uri, self.redirect_uri):
            raise ValueError("invalid_client")
        if resource != self.resource or response_type != "code" or code_challenge_method != "S256":
            raise ValueError("invalid_request")
        if scope != "gway:read" or not isinstance(code_challenge, str) or len(code_challenge) != 43:
            raise ValueError("invalid_scope_or_pkce")
        if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in code_challenge):
            raise ValueError("invalid_pkce")
        if not isinstance(state, str) or not 8 <= len(state) <= 2048:
            raise ValueError("invalid_state")
        session = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        self.pending[session] = (csrf, code_challenge, state, time.monotonic() + 300)
        return session, _html(csrf)

    def connect(self, session, csrf, bearer):
        pending = self.pending.pop(session, None)
        if pending is None or time.monotonic() > pending[3]:
            raise ValueError("expired_session")
        if not isinstance(csrf, str) or not hmac.compare_digest(csrf, pending[0]):
            raise ValueError("csrf_denied")
        if not self.registry.verify(bearer):
            raise ValueError("invalid_bearer")
        code = secrets.token_urlsafe(40)
        self.codes[hashlib.sha256(code.encode()).digest()] = (pending[1], time.monotonic() + 60)
        return self.redirect_uri + ("&" if "?" in self.redirect_uri else "?") + urlencode(
            {"code": code, "state": pending[2], "iss": "https://remote.arthexis.com"})

    def redeem(self, *, client_id, code, redirect_uri, code_verifier, grant_type, resource):
        if client_id != self.client_id or redirect_uri != self.redirect_uri or resource != self.resource or grant_type != "authorization_code":
            raise ValueError("invalid_grant")
        if not isinstance(code, str):
            raise ValueError("invalid_grant")
        stored = self.codes.pop(hashlib.sha256(code.encode()).digest(), None)
        if stored is None or time.monotonic() > stored[1] or not hmac.compare_digest(stored[0], _challenge(code_verifier) or ""):
            raise ValueError("invalid_grant")
        # A separate read-only credential is minted after console bearer proof.
        # These credentials carry only gway:read. No submit/admin capability.
        access = self.registry.issue(scope="gway:read", lifetime=3600)
        return {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "scope": "gway:read"}
