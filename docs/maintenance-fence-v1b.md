# MaintenanceFence V1-B — resource-scoped planning (#561)

V1-A is already merged in main as the pure state/receipt contract.
V1-B adds **only** a pure, deterministic resource planner and hermetic tests.
It does not acquire locks, coordinate across processes, persist a journal,
authenticate identities, read nodes, execute commands or change any deployment.

## Scope and naming

Resources use one of these canonical forms:

- `node/gway-001` — exclusive whole-node maintenance.
- `node/gway-001/deploy/ocpp-simulator` — an appliance deployment.
- `node/gway-001/service/ocpp-csms` — service operation.
- `node/gway-001/network/nftables` — network operation.
- `node/gway-001/database/ocpp-csms` — database operation.

The parser also accepts `ocpp-abb-N` nodes and kind labels `filesystem`
and `maintenance`; no new authority is conveyed by an accepted name.
Only canonical lowercase ASCII names within length/size limits are valid.

All resources are modeled as **exclusive**. Two resources conflict iff equal,
or one is an ancestor of the other on a slash-delimited segment boundary.
Siblings do not conflict unless the caller declares an additional shared
resource. A whole-node resource conflicts with every child of that node.

`plan(resources)` rejects malformed/unbounded input, normalizes duplicates,
subsumes descendants under an ancestor, and sorts keys deterministically.
`conflicts(a,b)` compares two such immutable plans; `acquire_order(plan)`
returns stable key ordering for a future atomic arbitration backend.

## Critical limitations

No claim that any lock has been acquired follows from a `ResourcePlan`.
Callers must conservatively enumerate **every** resource they may affect.
Missing network/database/service resources can cause a false conclusion of
independence, even when `conflicts()` behaves correctly. The resource planner
is a consistency helper, not a proof of complete operational scope.

Deterministic ordering alone does not prevent races or grant atomic multi-lock
acquisition. A future coordinator must atomically arbitrate the **entire**
resource set, preserve durable ownership and terminal receipts, enforce
fencing at real side effects, and fail closed on uncertain journal state.
V1-A's SHA-256 correlation token is not a cryptographic capability.

No integration with the existing simulator deploy lock, GitHub workflow,
AgentOps, MCP, node_exec, Ansible, CSMS or release paths is included.
The auto-install schedule remains unchanged. Issue #561 remains open,
R6 remains unchecked and BeforeAvailable remains Quarantined.

## Hermetic acceptance

Run:

```sh
python -m unittest tests.core.test_maintenance_fence_resources -v
```

Tests cover idempotent canonicalization, whole-node vs child conflict,
independent deployment siblings, shared network resource, invalid paths,
resource bounds, forged plans, immutable plans and deterministic ordering.

## Future work (separately authorized)

A real MaintenanceFence backend needs authenticated owner identity,
an atomic multi-resource lock with no stale-owner window, crash-safe journal,
boot-aware lease observations, monotonic fencing, uncertain recovery and
consumption by **every** relevant execution entrypoint. It must be audited
against the existing `deploy.sh` flock and GitHub workflow concurrency.
Only then can this contract support operational maintenance.

## Rollback

Revert this module, test file and document. No deployed state exists.
