# Watchtower autonomous MCP discovery and direct satellite management

Related: [gway-remote #264](https://github.com/arthexis/gway-remote/issues/264)
(closed as not planned); the new work does not reopen the former hub-routing design.

## Intended availability boundary

- Watchtower owns OAuth, authoritative enrollment/attestation and the externally
  visible MCP protocol. It must remain discoverable when gway-001 is offline.
- Every enrolled and explicitly admitted satellite owns its bounded node
  executor and provider manifest. Watchtower authenticates, selects a pinned
  private transport, and routes to that satellite directly.
- gway-001 owns AgentOps, Odoo and other 001-local services, but must **not**
  be a required transport hop for an operation targeting another node.
- A missing or revoked node, non-attested SSH host identity, stale inventory,
  missing transport, or unavailable execution receipt fails closed.
- Watchtower is a relay/registry/authorization boundary, not an operator shell.

## PR sequence

1. **P1 — Autonomous gateway discovery (this PR).** Preserve the existing
   upstream path on success; on transport failure, use the locally versioned
   gateway-owned initialize/tools/list schema and the current attested
   federation only. Do not advertise cached or absent 001-backend GitHub tools;
   keep OAuth, error handling, method allowlist and scopes intact. Align
   mcp_catalog_inspect with tools/list. Use bounded discovery deadlines.
   No node enrollment, SSH configuration, deployment or privilege change.
2. **P2 — Independently authorized per-node bridge (implementation in this PR).** Remove the fixed
   `audience=gway-001` in gateway/bridge bootstrap and dispatch. Select a
   current attested node based on the trusted registry and exact requested
   operation; bind each authenticated principal, scope, audience, request ID,
   known-host identity and revocation at call time. For node_result/cancel,
   recover the target from the durable original job receipt, never from a
   caller-supplied destination. Prove cross-node denial and no extra dispatch
   on retries, cancellation, UNCERTAIN transport and policy changes.
3. **P3 — Satellite rollout and offline-001 acceptance.** Validate provisioned
   relay/worker, strict SSH and independent installed release on gway-004,
   then gway-002. Resolve gway-005's currently unverified attestation in its
   own authorized enrollment workflow. Temporarily isolate only the 001 MCP
   backend under an approved maintenance window; ensure MCP discovery,
   node_list, bounded read/execute and correlated results on 002/004 continue
   while 001's own tools are explicitly unavailable. Preserve WireGuard
   star topology, no public satellite SSH and no AgentOps on satellites.

## P1 acceptance

- Valid authenticated legacy and modern initialize/tools/list remain available
  while the private 001 backend refuses connections.
- Only local/attested provider tools appear offline; no guessed or stale
  upstream-only GitHub/AgentOps tools, no new scope, no fallback shell.
- Healthy upstream retains its previous catalog, including backend-only tools.
- A backend HTTP authentication denial or malformed catalog is **not** an
  availability signal and must not be disguised as offline recovery.
- Unauthenticated clients, unapproved tools and backend-only tools continue
  to fail closed.
- CI is hermetic; no 001 or Watchtower change until separate approval.

## P2 bridge contract and rollout gate

The fixed `gway-001` bridge audience is replaced by a request-scoped audience
selected at Watchtower. `gway-000` is reserved exclusively for read-only
`node_list` / `node_capabilities`, and does not describe a real node. Every
other tool must use the current trusted pinned node transport. The bridge
session registers this audience from the authenticated HTTP gateway; the
HMAC-signed envelope alone is insufficient. Revalidate OAuth and target
eligibility on every dispatch, including read-only SSH operations.

For `node_result`, `node_cancel` and `node_deploy_status`, determine the
node from the existing durable request ledger **after checking principal
ownership**. An explicit destination on the latter must match that record;
retries, cancelled requests, and UNCERTAIN receipts must never be dispatched
to another node. Preserve cross-node request-ID deduplication and deny
unattested, unreachable, stale or missing transports.

Source/CI merge does **not** activate a new satellite or alter credentials,
WireGuard, SSH, services or deployments. Operator-specific Watchtower/runtime
validation and an offline-001 test remain P3 acceptance gates.
