"""C1/C2 Watchtower administrative passkey ceremonies, no privileged issuance.

Importable and testable, but NOT wired to OAuth, MCP, nginx or systemd.
Only an explicit, local administrative CLI can create enrollment grants.
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .watchtower_webauthn_ledger import WebAuthnLedger, _check_identifier
from .watchtower_webauthn_verify import verify_registration, verify_assertion, ORIGIN

MAX_BODY = 16384
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 19014
ADMIN_DB = "/var/lib/gway-webauthn/admin.sqlite3"


class AdminCeremonies:
    """No bearer/minting authority. All enrollment needs an offline grant."""

    def __init__(self, ledger):
        self.ledger = ledger

    def enrollment_begin(self, *, principal, grant):
        return self.ledger.start_enrollment(principal=principal, grant=grant)

    def enrollment_complete(self, *, principal, challenge, ticket, credential):
        principal = _check_identifier(principal)
        if not self.ledger.consume_enrollment_ticket(
                principal=principal, challenge=challenge, ticket=ticket):
            raise ValueError("invalid_or_expired_enrollment")
        verified = verify_registration(
            self.ledger, challenge=challenge, principal=principal,
            credential=credential)
        self.ledger._record_verified_credential(
            credential_id=verified.credential_id, principal=principal,
            public_key=verified.public_key, sign_count=verified.sign_count)
        return {"registered": True}

    def assertion_begin(self, *, principal, action, target):
        # Deliberately a proof challenge, not an administrative authorization.
        return self.ledger.begin(principal=principal, action=action, target=target)

    def assertion_complete(self, *, principal, action, target, challenge, credential):
        verify_assertion(self.ledger, principal=principal, action=action,
                         target=target, challenge=challenge, credential=credential)
        # No token, grant or reusable proof: future C3 must bind verification
        # to its privileged action within the same trusted server request.
        return {"verified": True}


ROUTES = {
    "/v1/enrollment/begin": ("enrollment_begin", frozenset({"principal", "grant"})),
    "/v1/enrollment/complete": ("enrollment_complete",
                               frozenset({"principal", "challenge", "ticket", "credential"})),
    "/v1/assertion/begin": ("assertion_begin", frozenset({"principal", "action", "target"})),
    "/v1/assertion/complete": ("assertion_complete",
                              frozenset({"principal", "action", "target", "challenge", "credential"})),
}


# Disabled unless a *trusted local runtime* explicitly injects an issuer.
# Never accept an issuer path or authorization from the HTTP request.
ISSUER_PATH = "/v1/bearer/issue"
ISSUER_FIELDS = frozenset({"principal", "scope", "lifetime", "challenge", "credential"})
COMBINED_OPTIONS_PATH = "/v1/bearer/combined/options"
COMBINED_FINISH_PATH = "/v1/bearer/combined/finish"
COMBINED_OPTIONS_FIELDS = frozenset({"principal", "intent"})
COMBINED_FINISH_FIELDS = frozenset({"principal", "intent", "challenge", "credential"})
REVOKE_OPTIONS_PATH = "/v1/bearer/revoke/options"
REVOKE_FINISH_PATH = "/v1/bearer/revoke/finish"


class AdminHandler(BaseHTTPRequestHandler):
    """Loopback-only HTTP adapter; no public forwarding in this increment."""

    def log_message(self, *_):
        # Never log URLs, credentials or enrollment grants.
        pass

    def _respond(self, status, result):
        body = json.dumps(result, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/v1/capabilities":
            self._respond(405, {"error": "method_not_allowed"})
            return
        if (self.headers.get("Host") != "%s:%d" % (LOOPBACK_HOST, LOOPBACK_PORT)
                or self.headers.get("Origin") not in (None, ORIGIN)):
            self._respond(403, {"error": "request_denied"})
            return
        from .watchtower_webauthn_verify import approved_origins
        try:
            permitted = approved_origins()
            enabled = (getattr(self.server, "issuer", None) is not None
                       and isinstance(permitted, list))
        except ValueError:
            enabled = False
        self._respond(200, {"passkeys_enabled": enabled,
                            "rp_id": "remote.arthexis.com" if enabled else None})

    def do_POST(self):
        # Reject unexpected host and browser cross-origin attempts even on
        # loopback; later HTTPS proxy requires a separately reviewed policy.
        if (self.headers.get("Host") != "%s:%d" % (LOOPBACK_HOST, LOOPBACK_PORT)
                or self.headers.get("Origin") not in (None, ORIGIN)
                or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json"
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Encoding")):
            self._respond(403, {"error": "request_denied"})
            return
        issuer = getattr(self.server, "issuer", None)
        # The legacy single-scope issuance path is intentionally never wired
        # to HTTP: its lifetime was not part of its WebAuthn challenge.
        if issuer is not None and self.path == COMBINED_OPTIONS_PATH:
            route = ("begin_combined", COMBINED_OPTIONS_FIELDS)
        elif issuer is not None and self.path == COMBINED_FINISH_PATH:
            route = ("issue_combined", COMBINED_FINISH_FIELDS)
        elif issuer is not None and self.path == REVOKE_OPTIONS_PATH:
            route = ("begin_revoke", COMBINED_OPTIONS_FIELDS)
        elif issuer is not None and self.path == REVOKE_FINISH_PATH:
            route = ("revoke_bearer", COMBINED_FINISH_FIELDS)
        else:
            route = ROUTES.get(self.path)
        if route is None:
            self._respond(404, {"error": "not_found"})
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
            if not 1 <= size <= MAX_BODY:
                raise ValueError()
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict) or payload.keys() != route[1]:
                raise ValueError()
        except (ValueError, TypeError, UnicodeDecodeError):
            self._respond(400, {"error": "invalid_request"})
            return
        try:
            provider = (issuer if route[0] in ("begin_combined", "issue_combined", "begin_revoke", "revoke_bearer")
                        else self.server.ceremonies)
            result = getattr(provider, route[0])(**payload)
        except Exception:
            # Generic response prevents leaking enrolled principals and keys.
            self._respond(403, {"error": "not_authorized"})
            return
        self._respond(200, result)


def serve(ceremonies, *, issuer=None):
    server = ThreadingHTTPServer((LOOPBACK_HOST, LOOPBACK_PORT), AdminHandler)
    server.ceremonies = ceremonies
    server.issuer = issuer
    server.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit local WebAuthn administration")
    parser.add_argument("--database", default=ADMIN_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser("grant", help="One-use passkey enrollment authorization")
    grant.add_argument("--principal", required=True)
    revoke = commands.add_parser("revoke", help="Revoke by registered credential ID")
    revoke.add_argument("--credential-id", required=True)
    listing = commands.add_parser("list", help="Read credential metadata, never keys")
    listing.add_argument("--principal", required=True)
    commands.add_parser("serve", help="Manually start loopback-only ceremony adapter")
    launch = commands.add_parser("serve-issuer", help="Explicit OFF-by-default privileged issuer")
    launch.add_argument("--bearer-database", default="/var/lib/gway-mcp/bearers.sqlite3")
    launch.add_argument("--receipts-database", default="/var/lib/gway-webauthn/receipts.sqlite3")
    args = parser.parse_args(argv)
    ledger = WebAuthnLedger(args.database)
    if args.command == "serve":
        serve(AdminCeremonies(ledger))
        return
    if args.command == "serve-issuer":
        if (os.geteuid() != 0
                or os.environ.get("GWAY_WEBAUTHN_ISSUER_ENABLED") != "1"):
            raise SystemExit("Watchtower admin issuer is disabled")
        raw = os.environ.get("GWAY_WEBAUTHN_ADMINISTRATORS", "")
        administrators = {v.strip() for v in raw.split(",") if v.strip()}
        if not administrators:
            raise SystemExit("Explicit administrator allowlist required")
        from .mcp_bearer import BearerRegistry
        from .watchtower_webauthn_issuer import IssuanceLedger, WatchtowerBearerIssuer
        issuer = WatchtowerBearerIssuer(
            credentials=ledger, registry=BearerRegistry(args.bearer_database),
            receipts=IssuanceLedger(args.receipts_database),
            administrators=administrators)
        serve(AdminCeremonies(ledger), issuer=issuer)
        return
    if os.geteuid() != 0:
        raise SystemExit("Only the local Watchtower administrator may manage passkeys")
    if args.command == "grant":
        # Prevent an automated workflow from printing an enrollment credential
        # into CI logs or captured shell history.
        if not sys.stdout.isatty():
            raise SystemExit("An interactive administrative terminal is required")
        value = ledger.create_enrollment_grant(principal=args.principal)
        sys.stdout.write("Enrollment grant (shown once; expires in 600s): " + value + "\n")
    elif args.command == "revoke":
        print("revoked" if ledger.revoke(credential_id=args.credential_id) else "not_found")
    elif args.command == "list":
        print(json.dumps(ledger.credential_metadata(principal=args.principal)))


if __name__ == "__main__":
    main()
