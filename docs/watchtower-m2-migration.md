# M2: transfer Watchtower enrollment ownership to gway-remote

Decision (2026-10-22): **replace the active GWAY/sampler enrollment server with a
gway-remote-owned server**, not another GWAY sampler release. Issue #199's M1b
receipt is runtime evidence, not authorization to change the server.

## Single-owner contract

- gway-remote owns HTTP `POST /v1/enroll`, `GET /health`, the invitation
  registry, peer allocation, durable operation receipts, CLI administration,
  systemd unit and Watchtower Ansible deployment. Remove dependence on
  `gway wire server serve` and `sampler/wire/__init__.py`.
- Preserve the existing public `register.gelectriic.com` hostname, exact
  Nginx routes and valid certificate; no redirect or public admin route.
- The existing `gway-wire-enroll.service` may be reused as a unit name if
  doing so produces a single service owner, but its ExecStart must become
  a `gway-remote` executable. Never leave two listeners behind the proxy.
- Distinguish registration HTTPS URL from the independently configured,
  externally validated WireGuard UDP endpoint. Do not inherit the stale
  `register.arthexis.com` or `arthexis` endpoint implicitly.
- Keep the existing unmanaged gway-001 peer and every pre-existing Peer block,
  `AllowedIPs`, key and WireGuard network setting byte-preserved where possible.
  Do not rotate keys, renumber addresses or restart the interface at cutover.
- Local invitation management is authenticated SSH + sudo, not exposed to
  the public HTTP listener. Tokens only in JSON POST bodies, stored as digests,
  never in query strings, headers, logs, exception texts, or command argv.
- Use `wireguard_enrollment_contract.py` for input validation. This is
  intentionally only a pure parser, **not** a running enrollment service.

## Durable state and transaction sequencing

Existing offline `wireguard_invitations.InvitationStore` is a useful precursor,
but its `redeem()` consumes a token before peer provisioning and **must not**
be called directly by the production POST handler.

A single SQLite registry must include invitations, devices, allocated /32s and
durable operation receipts. Under `BEGIN IMMEDIATE`, reserve allocation and
record an in-progress operation; include all persistent and runtime peer
addresses when computing occupied space. Preserve existing unmanaged peers.
Do not consume the invitation until persistent config and runtime peer state
are verified. Reconcile interrupted operations deterministically on restart
before accepting another enrollment; retry with the same device/public key
must be safe, different-key reuse must fail. Persist an explicit rollback/
restore outcome; do not rely on config-file atomic replacement alone.

Backup protected config (0600 root only), use a same-filesystem atomic replace,
verify the written file, apply with `wg set` only when safe, confirm current
state and commit the operation. Tests must inject failure at every step and
verify that retries neither duplicate addresses nor remove unmanaged peers.
Do not print raw keys, tokens or full configurations in test failures.

## Deployment and acceptance

1. Implement the server, registry and operator CLI in this repo with isolated
   unit/integration tests. Use loopback-bound Python HTTP; no HTTP admin route.
2. Add Watchtower-specific Ansible deployment/rollback and Nginx exact routes
   with explicit token-safe access logging. No unexpected `gway-001` deployment.
3. Before touching production, resolve HTTPS and WireGuard endpoint names,
   inspect provider firewall rules with authorized AWS access, check backup/
   restore steps, and record initial peer/config and service metadata.
4. Stage the gway-remote server on an alternate loopback port, with **no
   permission to mutate production WireGuard**. Test `/health` and invalid
   enrollment responses only, with dummy tokens.
5. Back up the existing unit/config/registry. Switch exactly one Nginx upstream
   and service owner during a deliberate cutover; keep public invitations
   disabled until full validation. Do not delete the old GWAY release first.
6. Verify Gway-001 latest handshake/transfer counters, exact Nginx routes,
   installed gway-remote SHA, returned approved endpoint, strict state
   permissions and zero public admin routes. If any gate fails, revert
   upstream/service without undoing the existing tunnel.
7. After a fully successful field enrollment of a test device and explicit
   acceptance, disable the legacy sampler unit/dependency and retire dead
   installation paths. Do not migrate or destroy opaque legacy registry
   records without an audited reconciliation.

PR CI: parser tests, registry crash/retry/replay/expiry/device-key/concurrency/
pool-exhaustion tests, unmanaged peer preservation, idempotent Ansible checks,
Nginx route/log policy tests and fake wg integration. Never run production
enrollment or call live `wg set` in PR CI.

**M2 is NOT production-ready merely because the parser or this document merges.**
Agent must post sanitized before/after receipts to the implementation issue;
field mutation only after reviewed code/PR CI and the above preflight gates.
