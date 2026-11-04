# Android v2 / #378 — B1: Watchtower WebAuthn contract

## Architectural boundary

Watchtower is the **sole administrative identity and authorization authority**. Android requests a privileged intent and presents an authenticator challenge; gway-001 executes an expressly authorized, named operation and retains its local secrets. Neither the Android API nor the MCP bearer verifier may directly access Watchtower's credential registry, perform passkey enrollment or mint bearer credentials.

**This increment is deliberately disconnected.** `watchtower_webauthn_ledger.py` is a private schema/intent ledger. It has no service/CLI/HTTP/MCP entry point, no authenticator verifier, no issuance path and no production database migration. A matching `consume()` only invalidates an intent; it **must never** count as evidence that WebAuthn authentication passed. The private `_record_verified_credential` persistence sink is not a registration API.

## WebAuthn configuration to validate in B2

- RP ID: `remote.arthexis.com`; expected HTTPS web origin: `https://remote.arthexis.com`. A native Android client must use a verified Digital Asset Links association between this web RP and the **release-signed Android package** before Credential Manager may use this passkey. Verify the production signing certificate fingerprint; do not hardcode a debug signing identity.
- Register using standard WebAuthn `navigator.credentials.create` / FIDO2 through an audited verifier (or Credential Manager passkey bridge); verify `clientDataJSON.type=webauthn.create`, challenge, origin, authenticator RP ID hash, UP/UV policy, credential ID/public key algorithm, and cryptographic attestation/authenticator data before storing. Explicit administrative bootstrap is required.
- Authenticate using `webauthn.get`; verify signature over `authenticatorData || SHA256(clientDataJSON)`, origin, RP hash, challenge, registered non-revoked credential ID, user presence **and user verification**, and sign counter policy (including synced passkey semantics). No unverified caller-provided `principal` may select an administrative identity.
- Authentication challenge bound to the **authenticated principal, exact action and target**. B1 supports `passkey.enroll`, `bearer.issue`, `secret.reveal`, `secret.update`. No general shell command, wildcard, or arbitrary path. New privileged operations must be separately reviewed and allowlisted.
- Challenges are random, SHA-256 hashed in SQLite, single use and expire after **120 seconds**. Mismatched action/target/principal burns the challenge; consumed requests cannot be replayed after process restart. This intent binding alone is **not** authorization.
- Require an operation-specific, short-lived server-side authorization after successful WebAuthn assertion. Bind it to the exact requested action and target; perform atomic consume with privileged operation. Do not persist raw bearer tokens, secret contents, clientDataJSON, signatures or challenges in logs.
- Enrollment: existing administrator grants one narrowly scoped, expiring enrollment opportunity; passkey never self-enrolls from fresh APK or from possession of the mobile API bearer. Separate offline administrative recovery and revocation. Revocation of a passkey must stop future administrative actions but must not silently revoke an unrelated existing ChatGPT OAuth connection unless deliberately configured.
- API/CSRF: exact HTTPS host/origin, bounded body sizes, strict no-store, CSRF protection for browser session routes, rate limiting, no caching of sensitive responses; public OAuth linker and MCP read-only gateway stay separate.

## B1 persistence and operations

`WebAuthnLedger` creates a private SQLite file (`0600`) containing credential public-key records and one-use challenge digests. It exposes internal begin/consume/revoke/metadata operations with no network bindings. Metadata intentionally omits key bytes. Production paths, directory ownership/Ansible permissions, multi-process limits, backup encryption and rotation are to be reviewed in B2/C before deployment. No application loads the module.

## Acceptance and next phase

Unit tests under `tests/infrastructure/test_watchtower_webauthn_ledger.py` cover unique challenges, action/target/identity isolation, expiry boundary, consumption/replay across instances, revoked credentials, idempotence, path permissions, metadata redaction, and explicit absence of issuer/verifier methods.

B2 should select an audited WebAuthn verification library compatible with Ubuntu 22.04 / Python 3.10, add verifier-side contract tests including malformed origin/JSON, invalid signature, RP ID, UV, enrollment takeover, cloned credential and sign counter, and agree on a safe, **explicitly invoked** bootstrap procedure. C is the first increment allowed to wire a private authorization service and token issuance, with a staged rollout/rollback and no credential changes on deploy.

The existing automatic Watchtower GitHub/Ansible deployment remains the recovery route independent of WebAuthn. Deploying code must never create an administrator or register a passkey automatically.
