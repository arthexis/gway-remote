"""One-time bearer-link browser flow for a pre-registered OAuth client.

Do not deploy as a public service before the OAuth transport and client
acceptance tests are completed. This component never exposes token issuance
through MCP or Agent Ops.
"""
import base64
import hashlib
from html import escape
import hmac
import re
import secrets
import time
import threading
from functools import wraps
from urllib.parse import urlencode, urlsplit

from .mcp_bearer import BearerRegistry, _lookup

MAX_PENDING = 1024

RESOURCE = "https://remote.arthexis.com/mcp"
ISSUER = "https://remote.arthexis.com"


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


def _callback_origin(redirect):
    """Build a CSP source from protected configuration, never request input."""
    try:
        if not isinstance(redirect, str) or any(ord(char) <= 32 or ord(char) == 127 for char in redirect):
            raise ValueError()
        parsed = urlsplit(redirect)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.fragment
                or parsed.username is not None or parsed.password is not None
                or parsed.netloc.endswith(":")
                or not re.fullmatch(r"[A-Za-z0-9.\[\]:-]+", parsed.netloc)
                or (parsed.port is not None and parsed.port < 1)):
            raise ValueError()
    except ValueError:
        raise ValueError("pre_registered_https_redirect_required") from None
    return "https://" + parsed.netloc


OAUTH_PAGE_STYLE = ("<style>body{font:1rem system-ui;background:#111827;color:#f9fafb;"
            "padding:3rem 1rem}main{max-width:30rem;margin:auto}"
            "input{box-sizing:border-box;width:100%;padding:.85rem;margin:.8rem 0;"
            "font-size:1rem;border-radius:.5rem}button{padding:.85rem 1.4rem;"
            "border:0;border-radius:.5rem;cursor:pointer}</style>")


def _html(form_token, *, requested_scope="gway:read", selectable=False):
    """Show the requested scope. Only missing client scope permits user selection."""
    scope_text = escape(requested_scope, quote=True)
    scope_choice = (
        "<p>Client requested: <strong>" + scope_text + "</strong>.</p>"
        "<fieldset><legend>Authorize this connection</legend>"
        "<label><input type='radio' name='scope' value='gway:read' checked>"
        " Read-only (read bearer)</label>"
        "<label><input type='radio' name='scope' value='gway:execute'>"
        " Read and execute commands (execute bearer; explicitly grants broader access)"
        "</label></fieldset>"
        if selectable else
        "<p>Requested permission: <strong>" + scope_text + "</strong></p>"
    )
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Connect GWA Remote</title>"
            + OAUTH_PAGE_STYLE
            + "<style>input[type=radio]{width:auto;margin:.6rem .4rem;padding:0}fieldset label{display:block}</style></head><body>"
            "<main><h1>Connect GWA Remote</h1><p>Enter a GWay Remote bearer "
            "issued on Watchtower for the permission shown below. The proof is "
            "not stored in the browser session.</p>"
            "<form method='post' action='/connect'>"
            + scope_choice
            + "<input type='hidden' name='csrf' value='" + escape(form_token, quote=True) + "'>"
            "<label for='bearer'>GWay Remote bearer token</label>"
            "<input id='bearer' name='bearer' type='password' autocomplete='off' "
            "autocapitalize='off' spellcheck='false' required>"
            "<button type='submit'>Connect</button></form></main></body></html>")


def _connect_error(scope):
    """Helpful but non-oracular error: never disclose whether a proof exists."""
    requested = escape(scope, quote=True)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>GWA Remote connection denied</title>" + OAUTH_PAGE_STYLE
            + "</head><body><main><h1>Connection not authorized</h1>"
            "<p>The requested permission was <strong>" + requested + "</strong>. "
            "Use a valid bearer with that scope. For command execution, reconnect "
            "from ChatGPT requesting <code>gway:execute</code> and enter an "
            "execute-scoped bearer issued on Watchtower.</p>"
            "<p>Start a new connection from ChatGPT; this form cannot be reused. "
            "No token information is displayed.</p></main></body></html>")


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class LinkFlow:
    """Ephemeral browser state; no token retained in session state."""
    def __init__(self, registry, *, client_id, redirect_uri, resource=RESOURCE):
        if not client_id or not _safe_redirect(redirect_uri, redirect_uri):
            raise ValueError("pre_registered_https_redirect_required")
        if resource != RESOURCE:
            raise ValueError("unexpected_resource")
        self.callback_origin = _callback_origin(redirect_uri)
        self.registry = registry
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.resource = resource
        self._lock = threading.RLock()
        self.pending = {}
        self.codes = {}

    def _purge(self):
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if v[3] > now}
        self.codes = {k: v for k, v in self.codes.items() if v[1] > now}

    @_serialized
    def begin(self, *, client_id, redirect_uri, resource, response_type,
              code_challenge, code_challenge_method, state, scope=None):
        if client_id != self.client_id or not _safe_redirect(redirect_uri, self.redirect_uri):
            raise ValueError("invalid_client")
        if resource != self.resource or response_type != "code" or code_challenge_method != "S256":
            raise ValueError("invalid_request")
        if scope not in (None, "gway:read", "gway:execute") or not isinstance(code_challenge, str) or len(code_challenge) != 43:
            raise ValueError("invalid_scope_or_pkce")
        if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in code_challenge):
            raise ValueError("invalid_pkce")
        if not isinstance(state, str) or not 8 <= len(state) <= 2048:
            raise ValueError("invalid_state")
        self._purge()
        if len(self.pending) + len(self.codes) >= MAX_PENDING:
            raise ValueError("link_capacity_reached")
        session = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        # Explicit operator consent can grant a broader scope than a read-only
        # client requested (RFC 6749 section 3.3). The token response carries
        # the actual scope; no implicit escalation is permitted.
        selectable = scope in (None, "gway:read")
        self.pending[session] = (csrf, code_challenge, state, time.monotonic() + 300,
                                 scope or "gway:read", selectable)
        return session, _html(csrf, requested_scope=scope or "gway:read", selectable=selectable)

    @_serialized
    def connect(self, session, csrf, bearer, *, selected_scope=None):
        pending = self.pending.pop(session, None)
        if pending is None:
            raise ValueError("session_unavailable")
        if time.monotonic() > pending[3]:
            raise ValueError("expired_session")
        if not isinstance(csrf, str) or not hmac.compare_digest(csrf, pending[0]):
            raise ValueError("csrf_denied")
        scope = pending[4]
        if selected_scope is not None:
            if not pending[5] or selected_scope not in ("gway:read", "gway:execute"):
                raise ValueError("scope_selection_denied")
            scope = selected_scope
        if not self.registry.verify(bearer, required_scope=scope):
            raise ValueError("invalid_bearer")
        code = secrets.token_urlsafe(40)
        self.codes[hashlib.sha256(code.encode()).digest()] = (pending[1], time.monotonic() + 60, bearer.split("_", 2)[1], scope)
        return self.redirect_uri + ("&" if "?" in self.redirect_uri else "?") + urlencode(
            {"code": code, "state": pending[2], "iss": ISSUER})


    def authorization_error_redirect(self, *, client_id, redirect_uri, state, error="invalid_request"):
        """RFC 9207: return issuer on safe, client-bound OAuth error redirects.

        Never redirect to a caller-supplied callback unless it exactly matches
        the pre-registered client. Invalid clients stay local HTTP 400.
        """
        if (client_id != self.client_id or
                not isinstance(redirect_uri, str) or
                not _safe_redirect(redirect_uri, self.redirect_uri) or
                not isinstance(state, str) or not 8 <= len(state) <= 2048):
            return None
        if error not in ("invalid_request", "invalid_scope", "unsupported_response_type"):
            error = "invalid_request"
        return self.redirect_uri + ("&" if "?" in self.redirect_uri else "?") + urlencode(
            {"error": error, "state": state, "iss": ISSUER})

    @_serialized
    def redeem(self, *, client_id, code, redirect_uri, code_verifier, grant_type, resource):
        if client_id != self.client_id or redirect_uri != self.redirect_uri or resource != self.resource or grant_type != "authorization_code":
            raise ValueError("invalid_grant")
        if not isinstance(code, str):
            raise ValueError("invalid_grant")
        stored = self.codes.pop(hashlib.sha256(code.encode()).digest(), None)
        if stored is None or time.monotonic() > stored[1] or not hmac.compare_digest(stored[0], _challenge(code_verifier) or ""):
            raise ValueError("invalid_grant")
        # The requested scope must match the pre-issued operator credential.
        # The derived credential cannot outlive or exceed its parent.
        access = self.registry.issue(scope=stored[3], lifetime=3600, parent_id=stored[2])
        expires = _lookup(self.registry.path, access.split("_", 2)[1])[2]
        return {"access_token": access, "token_type": "Bearer", "expires_in": max(0, expires - int(time.time())), "scope": stored[3]}
