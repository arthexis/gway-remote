# Multi-node MCP execution correction (gway-002)

## Confirmed regression

- `node_exec(hostname)` succeeds on gway-001 and returns `Execution request rejected` on gway-002.
- gway-002 is attested, reachable, and execution-eligible; preview succeeds.
- `PinnedNode.__post_init__` rejects every node except gway-001.
- `load_service` resolves only gway-001 from the trusted enrollment snapshot.
- `AuthorizedExecution.exec` requires the requested node to equal the single transport node.

## Required implementation before merge

1. Resolve each requested node from a fresh root-published inventory snapshot, not from caller-supplied SSH addresses or keys.
2. Pin per-node SSH host identity, alias, address and relay user to trusted operator-managed configuration; fail closed for missing/ambiguous entries.
3. Replace the single-node relay with per-node transport selection while preserving request ownership, durable idempotency, and host-key binding for result/cancel.
4. Preserve gway-001 behavior and allow gway-002 only after its trusted transport configuration and forced-command relay are provisioned.
5. Make preview limits use the selected node's transport; report unavailable when no relay is configured, rather than claiming that grant alone enables execution.
6. Add tests for both nodes, unknown nodes, host-key mismatch, revoked grant, stale inventory, SSH failures, and request replay across nodes.
7. Validate on Watchtower: `node_exec(hostname)` and `node_result` for both nodes, plus deployment rollback and service reload.

## Safety

Do not remove SSH host-key checking, expand MCP shell privileges, or reuse gway-001's host identity for gway-002. This PR remains draft until code and tests are implemented.
