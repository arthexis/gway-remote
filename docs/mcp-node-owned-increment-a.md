# Increment A: node-owned MCP dispatch — implementation contract

This is an incremental migration contract, **not** authorization to activate the public proxy.

## Existing boundaries

- Watchtower is authoritative for enrollment, attestation, node access policy, and the WireGuard peer mapping.
- Each node is authoritative for its MCP `tools/list` and `tools/call` application catalog.
- Watchtower must not expose its root-owned enrollment ledger, grant unrestricted access to its execution broker, or accept arbitrary upstream addresses from MCP clients.
- The current Watchtower gateway combines upstream tools with `NODE_TOOLS` and `EXEC_TOOLS`. It also performs scope checks. This remains the production path until equivalent protections are verified.

## Required implementation before changing routing

1. **Internal protocol**: define a versioned, bounded node-router request envelope containing an authenticated principal, node identity, permitted scopes, request ID and expiry. Bind the audience to the intended node. Reject replay, unknown node, stale identity, and missing scopes. Do not trust client-supplied identity headers.
2. **Enrollment**: retain the single Watchtower enrollment ledger. Provide a narrowly scoped, authenticated read/preview service or signed short-lived inventory snapshot; never copy or mount the root database on a node.
3. **Execution**: keep the existing operator authorization and node execution eligibility checks at Watchtower. If a node requests relay execution, it must use a narrowly scoped internal API that cannot select arbitrary nodes or elevate privileges. Execution and result retrieval must remain tied to the originating principal and request.
4. **Node MCP**: node HTTP transport advertises and dispatches the complete tool set, with tool-specific scope enforcement. Do not assume a read-only bearer token authorizes execution.
5. **Ansible**: provision the internal service credentials, file ownership, systemd units, firewall/WireGuard access, rotation and health checks idempotently. No manual steps unless truly impossible to standardize.
6. **Compatibility**: preserve current MCP protocol negotiation, OAuth challenges, error shapes and bounded response behavior; test both legacy and modern clients.
7. **Rollout**: test the node-side service independently, then shadow-compare catalogs. Public `/mcp` must remain unchanged until the next increment's reversible routing cutover.

## Acceptance gates

- Exact current tool contract parity, with no missing or unexpectedly added tools.
- Cross-principal, cross-node, replay and stale-credential attempts denied.
- Unavailable inventory or executor fails closed; no fallthrough to shell.
- Integration tests for list/call, read/execute scopes, preview/result/cancel, and concurrent sessions.
- Ansible syntax/idempotency and CI pass on the final commit; operator verifies a live pilot on gway-001.
- Keep this PR unmerged until all gates are met.
