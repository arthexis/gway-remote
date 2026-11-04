# WebAuthn C3: one-time bearer issuance (inactive until C4)

Tracking #378, based on C1/C2 (#385). This increment adds a **private
issuer** with real WebAuthn authentication and an optional loopback-only
handler. It does not enable production HTTP, create a systemd unit, configure
Nginx, change Android or create/enroll an administrator.

## Security and authorization

1. Watchtower is the sole issuer and authority. The issuer constructor
   requires an explicit allowlist of administrative principal IDs obtained
   from trusted configuration. No request parameter can add an administrator.
2. To issue a token, the client first obtains a 120-second challenge for
   action `bearer.issue` and server-defined target `gway-execute` or
   `gway-read`. The completion request contains **that** challenge and a
   new WebAuthn assertion. The issuer consumes the challenge, verifies
   FIDO2 RP ID/origin/signature/UV/credential revocation and sign counter,
   then invokes `BearerRegistry.issue(operator_approved=True)` in the
   **same trusted server call**. A prior generic `verified:true` response
   never conveys authority.
3. Scope must be exactly `gway:execute` or `gway:read`. Default policy is
   an explicit requested lifetime within 60 seconds and 30 days. A newly
   issued bearer is independent of earlier bearers; no automatic revocation
   or changes to OAuth/ChatGPT refresh tokens.
4. Limit issuance to **three attempts after successful WebAuthn verification
   per principal per rolling hour**, using private SQLite (mode 0600)
   transactions. The quota survives restarts and is shared across workers.
   The receipt contains principal, credential ID, scope, timestamp and
   generated bearer **ID**, never the bearer secret.
5. Return the plaintext token only in a one-time JSON response with
   `Cache-Control: no-store`. Neither the issuer nor the HTTP adapter logs
   request payloads, responses, signatures or bearer values. The underlying
   `BearerRegistry` persists only SHA-256 digests.
6. Fail closed for unknown principals, mismatched scope/target, invalid
   signature, missing user verification, replay, revoked credentials,
   counter rollback, quota exhaustion, invalid lifespan or malformed HTTP.
   Errors return generic denial responses.

**Important:** Existing registry semantics retain scope separation; issuing
`gway:execute` creates an execute credential for the existing execute-scoped
ChatGPT connection, which already includes operational read tools. No implicit
read-scoped OAuth grant is created or escalated. The credential must be
reconnected to ChatGPT using the matching `gway:execute` permission.

## Activation boundary

`watchtower_webauthn_issuer.py` contains `WatchtowerBearerIssuer` and
`IssuanceLedger`. C3 adds `/v1/bearer/issue` to the *optional* C2 loopback
handler, but its default is **404**: the existing `serve` CLI does not
instantiate or inject any issuer. This cannot be enabled by changing a
request field, sending a bearer or guessing a URL.

C4 must provision a dedicated administrative service identity, protected
bearer/credential registry permissions, reviewed package dependencies,
rate limits for *challenge creation and failed authentication* in addition
to the successful issuance quota, explicit HTTPS reverse-proxy/origin
policies, hardened systemd unit, health checks and transactional rollback.
The service MUST NOT run as root or share the MCP read-only verifier
identity. Additional audit is required for revocation racing issuance
across separate SQLite databases; the current issuer checks revocation
again immediately before issue but does not claim cross-DB atomicity.

**Do not expose the optional endpoint publicly or use production tokens
for tests until C4 has satisfied these controls.** Automatic Watchtower
deployment may stage this inert module but does not provision or enable it.

## Verification

`tests/infrastructure/test_watchtower_webauthn_issuer.py` uses an actual
ephemeral P-256 authenticator in signed WebAuthn responses and tests
successful execute/read issuance, verifier acceptance and scope restrictions,
previous bearer survival, replay, corrupted signature, wrong target,
unauthorized principal, expiry bounds, revocation, quota persistence and
HTTP disabled-by-default/exact-input gates. No production credentials
are used. CI also runs this suite on Ubuntu 22.04/Python 3.10.
