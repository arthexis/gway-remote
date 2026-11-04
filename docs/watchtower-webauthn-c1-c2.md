# WebAuthn C1 + C2 — operator enrollment and isolated ceremonies

Tracks #378. These components are deliberately **not activated** by the
existing Ansible Watchtower deployment. C3 owns bearer issuance; C4 owns the
dedicated service identity, runtime dependency provisioning, HTTPS routing,
rate limiting, transaction safety and rollback. No credential is registered
by merging code or deploying the existing MCP services.

## Authority and initial bootstrap (C1)

Watchtower remains the authority, not gway-001 or Android. An operator with
**local root access to Watchtower** may create one narrowly scoped
enrollment authorization, bound to a principal. Never run this command
through MCP, Agent Ops, automation, CI, or remote conversation; grant output
requires an interactive terminal and is sensitive.

For a future explicitly provisioned and restricted local administration:

```bash
sudo python3 -m gway_remote.watchtower_webauthn_admin grant --principal admin
```

This command is an **operator procedure specification**, not a promise that
production Python dependencies or the administrative service are installed.
It creates a private 0600 database only when deliberately invoked. An
enrollment grant expires in 600 seconds, is stored as a digest and may
initiate exactly one enrollment. Once redeemed, a separate random
enrollment ticket binds the principal to a 120-second WebAuthn challenge.
Neither the grant nor the ticket authorizes bearer issuance. A failed
attestation consumes the ticket, requiring a new grant.

The grant must travel to the intended browser/app by a secure operator
channel; do not paste it into chat, issues or CI. C4 must settle the exact
privileged CLI / dedicated service-user permissions **before enabling the
HTTP adapter**, since the initial 0600 database owner is the local CLI
identity. Do not run a persistent root-owned network service as a shortcut.

After an existing operator authenticates by the approved offline recovery
route, local administration may revoke a known credential ID:

```bash
sudo python3 -m gway_remote.watchtower_webauthn_admin list --principal admin
sudo python3 -m gway_remote.watchtower_webauthn_admin revoke --credential-id <ID>
```

This cannot reveal private keys and does not automatically revoke existing
MCP bearer/OAuth credentials. Grant creation and recovery are **not**
available through the C2 HTTP interface.

## C2 ceremony adapter (loopback only, inactive)

`gway_remote/watchtower_webauthn_admin.py` provides an importable
`AdminCeremonies` and a standard-library HTTP adapter bound strictly to
`127.0.0.1:19014` when invoked explicitly with `serve`. It is not
started or reverse-proxied by existing Watchtower Ansible. No nginx
routes, OAuth hooks or MCP tools are added.

All routes accept exact JSON payloads via POST, bounded at 16 KiB:

| Path | Required keys | Effect |
| --- | --- | --- |
| /v1/enrollment/begin | principal, grant | Redeem operator grant; return challenge+ticket |
| /v1/enrollment/complete | principal, challenge, ticket, credential | Burn ticket, verify WebAuthn registration, store public key |
| /v1/assertion/begin | principal, action, target | Return one-use action-bound challenge, **not** permission |
| /v1/assertion/complete | principal, action, target, challenge, credential | Verify registered passkey, update counter; return only `verified:true` |

The transport rejects unknown routes, unexpected Host/Origin, extra JSON
fields and non-JSON input. Responses use `Cache-Control: no-store` and
do not echo grants, assertions or keys. The HTTP handler logs no request
content. A successful assertion never creates a reusable authorization
grant, cookie, bearer, session or privileged operation.

WebAuthn `py_webauthn==3.0.1` verifies RP ID, HTTPS origin, user verification
and signatures. Native Android Credential Manager additionally requires
a verified Digital Asset Links association for the signed package, deferred
to the Android integration.

## Security gate before public exposure

**Do not publish these HTTP endpoints directly or reverse-proxy them as
is.** For C3/C4, add a dedicated unprivileged identity with scoped DB
access, rate limits and concurrent request bounds, explicit HTTPS
routing with trusted proxy origin semantics, an independently authenticated
operator session, request-level authorization and atomic proof-to-action
binding. In particular, a JSON `verified:true` result is not a valid
permission for a subsequent separate HTTP request. The admin grant remains
offline only; no self-enrollment from a fresh APK or a bearer.

Rollback through the current GitHub/Ansible deployment remains independent
of WebAuthn. There is no new service unit, open listener or credential
migration in this PR.

## Acceptance evidence

`tests/infrastructure/test_watchtower_webauthn_admin.py` exercises real
ephemeral ES256/FIDO registration and assertion, grant replay/expiry,
identity binding, enrollment-ticket mismatch/expiry and rollback,
revocation and rejection of public issuance and malformed/foreign-origin
HTTP requests. Python 3.10 Ubuntu 22.04 and Python 3.11 CI run these tests.
No secret, bearer or real operator credential is needed.
