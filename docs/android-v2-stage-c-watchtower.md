# Watchtower WebAuthn Stage C — combined MCP bearer issuer

Tracking: [#378](https://github.com/arthexis/gway-remote/issues/378), follow-up Android UI stage D and secrets [#381](https://github.com/arthexis/gway-remote/issues/381).

## Implementation boundaries

Stage C extends the existing audited `watchtower_webauthn_ledger`,
`watchtower_webauthn_verify`, `watchtower_webauthn_admin` and
`watchtower_webauthn_issuer` modules, without adding a public MCP command,
Mobile API endpoint or nginx route. The isolated WebAuthn verifier uses the
`webauthn` Python library and requires UV, exact origin, RP ID, challenge,
signed authenticator data, current credential status and counter semantics.

Legacy bearer rows persist unchanged as a single scope. New administrator-
issued combined parent rows use the single canonical scope representation
`gway:execute gway:read`. The registry accepts **only** this exact combined
encoding or an existing valid single scope, never unrestricted arbitrary scope
strings. A combined parent can delegate **one** explicitly authorized OAuth
scope. Child OAuth credentials stay single-scope and never gain authority
merely because the parent has another scope. Ancestor revocation and expiry
continue to invalidate descendants. This is a no-copy, no-schema-migration
change to existing bearer credentials.

## Operator-controlled bootstrap

**No service or HTTP proxy is enabled by this PR.** The issuer has two gates:
(1) explicit `serve-issuer` invocation by the trusted administrative account
on Watchtower, and (2) `GWAY_WEBAUTHN_ISSUER_ENABLED=1` and an explicit
`GWAY_WEBAUTHN_ADMINISTRATORS` allowlist in protected administrator
configuration. The server binds only `127.0.0.1:19014`.
The regular `serve` command offers enrollment/assertion proof ceremonies
only; it does **not** expose the token-issuance endpoints.

For local operator use after a security review:
1. Install the isolated cryptographic dependency and test it under the Python
   version used by Watchtower. Never install dependencies by arbitrary HTTP request.
2. Confirm the pinned RP ID and origin (`remote.arthexis.com`), deployment
   identity, database ownership and filesystem permissions. The exact signed
   Android app ↔ origin association and HTTPS proxy remain **stage D blockers**.
3. Using a trusted interactive Watchtower console, invoke the existing
   administrator CLI `grant --principal <admin>` to create a short-lived
   one-use passkey-enrollment grant. **Do not copy its value into ChatGPT,
   GitHub, command-line arguments, logs or issues.** Register via the
   loopback-only ceremonies with a real platform passkey before issuance.
4. Run the explicitly gated `serve-issuer` command using protected environment
   and the deployed, reviewed Watchtower storage paths. It is intentionally
   not integrated into the current Ansible/watchtower release service. Do not
   expose this loopback port through nginx, tunnels, or an unrestricted relay.
5. Stage D must provide an audited, operator-authorized HTTPS transport (with
   explicit origin/Host/CSRF protections) and Credential Manager integration
   before any remote/mobile issuance can occur.

## Exact administrative API (internal loopback only)

With a server explicitly injected with the `WatchtowerBearerIssuer`:

- `POST /v1/bearer/combined/options`:
  `{"principal":"<admin>","intent":{"action":"issue_mcp_bearer","scopes":["gway:execute","gway:read"],"lifetime_seconds":86400,"request_id":"<32 hex>"}}`.
  Returns a challenge, RP ID, origin, action and expiry.
- `POST /v1/bearer/combined/finish`: identical principal+intent,
  `challenge` and a raw WebAuthn `credential` object with signed assertion.
  Only after successful verification and a persistent single-use receipt does
  the issuer mint the token. Returns `bearer` **one time** with
  `bearer_id`, `scopes`, `expires_in` and `Cache-Control: no-store`.

All action fields are bound to the WebAuthn challenge via canonical SHA-256.
The single-use challenge is consumed even if an assertion fails. A replay
cannot mint a second token; the receipt also has a durable unique
`request_id`. Receipts retain only operator, credential ID, requested scope,
timestamp and issued token ID. Existing OAuth token bodies remain hidden.
The existing per-admin issue limit is three per hour.

The legacy `POST /v1/bearer/issue` route remains compatible when the
trusted issuer is explicitly injected. It is **not** exposed by default and
is not required by Android v2. Its scope remains the legacy single-scope
form until removed with separate audited compatibility work.

## Revoke and recovery

Enrollment still requires a console-issued one-use grant; `list` only lists
credential IDs/timestamps/status, and `revoke` revokes a passkey ID under the
trusted administrator CLI. Operator loss-of-device response is revocation of
the passkey credential ID (not a device label), optional explicit revocation
of the affected MCP bearer IDs, and re-enrollment using a new console grant.
Outstanding OAuth children are invalidated when their bearer parent is revoked.
There is no public self-reset endpoint.

**Follow-up work:** Stage C does not add mobile access or secret-reveal/update
operations. #381 must implement a separately reviewed key allowlist, version
checks and no-value disclosure policy; do not interpret the current issuer as
general permission to read any file.

## QA

The dedicated integration suite uses genuine ES256 signed WebAuthn fixtures,
checks RP/origin and UV in the existing verifier suite, and adds combined
scope verification, legacy scope preservation, OAuth delegation/refresh,
persistent rate limits and idempotency, mutation of challenge-bound intent,
invalid signatures, missing UV, revocation, and HTTP off-by-default / Origin
checks. No production passkey or bearer is touched in CI.

### Rollback
Do not launch `serve-issuer` (default). If explicitly started during a later
authorized pilot, stop the manual service and unset the feature gate.
Existing single-scope and combined-scope tokens remain revocable using the
normal Watchtower administrator token registry. Do not delete or regenerate
the issuer's bearer SQLite database when rolling back.
