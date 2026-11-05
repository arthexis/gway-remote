# Android v2 — Stage B: Watchtower passkey authority contract

Status: **design only; no HTTP route, token issuer, enrollment or mobile UI is enabled by this change**.
Tracking: [#378](https://github.com/arthexis/gway-remote/issues/378) stages B–D;
secrets management [#381](https://github.com/arthexis/gway-remote/issues/381).

## Existing boundaries and decisions

* Watchtower alone is the source of authorization for GWay Remote MCP administrative bearer issuance.
  `gway_remote/mcp_bearer.py` currently stores token **digests**, not recoverable bearer strings;
  it currently stores **one** scope per credential. `gway_remote/mcp_link_http.py` is a
  ChatGPT OAuth-link endpoint, not an administrative token-issuance endpoint.
* Stage C MUST explicitly migrate the scope representation to a **set of scopes** with
  backward compatibility for current read-only and execute-only credentials. A newly issued
  administrative token MUST carry both `gway:read` and `gway:execute` so one token can
  authorize all ChatGPT MCP read/execute operations. Never make `gway:execute` silently
  imply `gway:read` on old tokens. OAuth linking must allow the one parent's granted scope set,
  while delegations cannot exceed the parent grant. Preserve legacy token acceptance.
* A passkey authenticates an **operator identity**, not an arbitrary Android installation.
  WebAuthn credentials are RP-bound and may be synced across devices. A UI device label is
  advisory, not proof of a hardware-bound key; recovery/revocation operate on credential IDs.
* Stage B produces an interface and threat model only. Stage C implements the hardened issuer
  and protocol verification; stage D integrates Android Credential Manager. **No passkey UI
  action, bearer issue path, or privilege escalation is added now.**

## Trust and deployment

* Fixed, operator-controlled HTTPS origin and RP ID must be configured in Watchtower **before**
  enrollment. Suggested starting point is the existing `https://remote.arthexis.com` origin
  with RP ID `remote.arthexis.com` **only if** the actual Android Credential Manager / browser
  WebAuthn origin and Android Digital Asset Links relationship support this arrangement.
  Stage C must validate the precise origin allowlist and RP ID after an end-to-end test, not
  trust a URL provided by the requester. Android native passkeys require a verified
  app-to-domain association; document and test `assetlinks.json` and the signing-certificate
  fingerprint rather than inventing an `android:apk-key-hash` or treating the HTTPS host as
  automatic app authorization.
* Enrollment and assertion endpoints are distinct from the existing MCP bearer gateway,
  the OAuth link service, and the ordinary Mobile API. A narrow Watchtower admin broker has
  the only ability to call the issuer with an attested administrator grant; the verifier
  and unprivileged mobile API may not use or import an issuing credential.
* No arbitrary `node_exec`, `sudo`, filesystem path, secret name, or remote host can be
  supplied via any authentication/issuance endpoint. Bearer issuer only operates on the
  Watchtower-owned bearer registry.

## Administrative enrollment

1. An administrator initiates a **short-lived one-use enrollment** on the Watchtower console
   with explicit identity and intent, not via Android or a generic MCP command. First
   enrollment requires a physically/operationally trusted bootstrap; no self-enrollment.
2. Android begins `POST /admin/v1/passkeys/enroll/options` using the bootstrap authorization
   out of band (one-time invitation); server resolves the operator from the bootstrap record.
   It returns a fresh random challenge (at least 32 bytes), server-provided `rp.id`,
   `user.id`, allowed algorithms, `authenticatorSelection.userVerification=required`,
   attestation policy, expiry and request handle. No client-supplied authority to choose RP
   or identity. Invitations are single-use, tightly rate-limited, and cannot be logged.
3. Android invokes Credential Manager `createCredential` using these exact options and posts
   the credential result and handle to `POST /admin/v1/passkeys/enroll/finish`.
4. Watchtower verifies: invitation one-use/expiry, challenge, exact RP ID hash, exact permitted
   origin, `clientDataJSON.type=webauthn.create`, registration attestation/authenticator
   data as required by selected attestation policy, supported algorithm and credential ID
   uniqueness, user verification flag, public-key encoding, and operator binding. Do not
   trust caller-provided `verified`, `userVerified`, `origin` or `signCount` flags.
   Challenges and enrollment grants are consumed **transactionally** whether successful
   or rejected at finish (prevent concurrent redemption).
5. Store only credential ID, public key, authorized operator ID, status, sign counter (if
   meaningful), timestamps and provenance. Secret private keys never leave the authenticator.
   Require a second independently attested administrator for adding a further credential
   to an existing operator **or** a new explicit Watchtower-console bootstrap. Never allow
   an existing MCP bearer to enroll or reset a passkey.

## Fresh step-up per sensitive operation

1. `POST /admin/v1/passkeys/assert/options` takes only an enumerated action intent, e.g.
   `issue_mcp_bearer`, `revoke_mcp_bearer`, `reveal_secret`, or `update_secret`.
   Secret operations also bind a canonical allowlisted key ID (not a path), version
   precondition and operation digest; they require their own authorization policy in #381.
   Token issuance binds the exact **requested scope set** and bounded lifetime.
2. Watchtower issues one challenge per transaction, valid for at most **120 seconds**, stores
   a hash of a random opaque challenge/transaction handle, operator ID, action,
   canonical request digest, allowed credential IDs, expiry and `consumed_at`.
   Use dedicated durable storage shared by concurrent workers, not per-process memory.
3. `POST /admin/v1/passkeys/assert/finish` carries the handle and raw WebAuthn assertion
   (clientDataJSON, authenticatorData, signature and credential ID), plus the **same**
   canonical request. The server resolves the original transaction; it never accepts a
   replacement action/lifetime/scope/key from the client.
4. WebAuthn library MUST verify signature with the registered public key over
   `authenticatorData || SHA256(clientDataJSON)`, `webauthn.get` type, exact challenge,
   pinned RP ID hash, exact origin allowlist, UP + UV flags, credential ID/operator identity,
   credential active status and authenticator counter semantics (including authenticators
   with zero counters). Reject missing UV. Cross-origin assertions are denied unless
   a specifically audited platform origin variant is configured.
5. Atomically mark the challenge consumed, **then authorize and perform exactly its bound
   action once**; keep idempotency state by request ID. Concurrent finish attempts cannot
   double-issue. For transient issuance errors after challenge consumption, require a new
   challenge rather than replay. Successful issuance returns bearer plaintext **once**
   over HTTPS in a `Cache-Control: no-store` response. Never persist plaintext.
6. All successful/failed attempts enforce per-operator, per-credential and source-IP
   rate limits with lockout and audit (bounded). Failures use generic errors with no
   account/credential enumeration. Never log challenges, assertions, private key material,
   bearer token bodies, secret values, authorization headers or full POST bodies.

## Issue and revoke contract

* `POST /admin/v1/mcp-bearers/issue/options` is **not** a second issuance method: the
  assertion/options action above binds `issue_mcp_bearer`, `scopes` exactly
  `["gway:execute","gway:read"]` (canonical sorted representation), `lifetime_seconds`
  (default 1 day, maximum 30 days, operator-policy override only if separately approved),
  and a caller-generated idempotency identifier.
* Finish produces `{key_id, bearer, scopes, expires_at}` once, under `no-store`;
  a second finish must not reveal the bearer again. No endpoint returns the plaintext
  of an existing credential. Follow-up operations list only `key_id`, scopes, expiry,
  revoked state and audit metadata.
* Explicit revocation binds `key_id` and requires a fresh assertion; no implicit revoke
  of another token upon issuance. Losing the phone/passkey revokes the **passkey**;
  outstanding MCP tokens require a separate incident-response revocation decision.
* The OAuth ChatGPT parent token can be pasted on its existing setup screen; the OAuth
  implementation must correctly represent the combined authorization rather than
  silently downscope or create execute-only read failures.

## Recovery, rotation and device loss

* At least two enrolled administrative passkeys or one separate sealed Watchtower-console
  recovery process should be configured before relying on mobile-only recovery.
* Recovery requires physical/admin console presence, verification of operator identity and
  an audited, one-use recovery authorization; **never** a public email-only reset, a link
  sent through MCP, an existing bearer, or a backup secret shipped inside the APK.
* Enumerate credentials by pseudonymous ID, creation/last-use time and revoked state.
  Revoke one credential immediately on reported device loss, invalidate all outstanding
  challenge handles for it and log the event; optionally revoke its issued bearers by
  recorded issuer association only with explicit operator confirmation.
* Syncable passkeys cannot guarantee single-device revocation: revoke credential ID or
  operator access, not merely the Android installation label.

## Threat model and mandatory hermetic negative checks (Stage C)

| Attack / failure | Required protection and test |
|---|---|
| Challenge reuse or concurrent finish | Durable single-use transactional consumption; second/parallel finish denied |
| Expired or unknown challenge | Deny before action, no issuance |
| Wrong RP ID or origin (incl. lookalikes) | Exact checks in trusted WebAuthn verifier; reject |
| Forged/incorrect assertion signature | Verify registered public key; reject |
| Missing UP or UV | Reject, never accept local biometric UI flag as proxy |
| Unknown/revoked credential or operator mismatch | Reject without enumeration |
| Mutated scopes, lifetime, action, key ID or version | Canonical action request digest mismatch; reject |
| Re-enroll without console bootstrap | Reject, including with valid MCP token |
| Replay after timeout/restart and parallel workers | Persist consumed/expired records; deny |
| CSRF, Origin and Host confusion, XSS | Fixed host, strict Origin and content type, CSRF on cookie-backed routes, no-store, strict CSP |
| Leaked device / stale session | Credential revocation + challenge invalidation; no cached issuing ability |
| Network interruption between commit and response | No second plaintext disclosure; operator must reissue then revoke stale key explicitly |
| Audit/screenshot/log leakage | Server fixed-schema audit with IDs/reasons only; Android sensitive UI `FLAG_SECURE` |
| Rate-limit bypass | Server bounded budgets plus persistence across processes/restarts |
| Existing OAuth regressions | Legacy read/execute tokens and OAuth pairing continue, combined-scope parent tested |
| Secret-store policy bypass | #381 action identity, key allowlist and version-bound writes; no direct file paths |

## Stage B acceptance / handoff

- This document is the agreed contract for C, D and #381, not evidence that any
  cryptographic verifier or passkey endpoint is implemented.
- Contract examples and hermetic negative tests may live in source-controlled fixtures;
  they do **not** issue tokens or authenticate people.
- Stage C ships behind an explicit off-by-default feature gate, isolated identities,
  real verifier-library tests and Watchtower-only administrative bootstrap.
- Stage D exposes Access MCP only when server feature discovery confirms the issuer and
  completes tests on the USB Android attached to gway-001; never fake it locally.
