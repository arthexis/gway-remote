# MaintenanceFence V1-A — pure contract (#561)

This stage adds only `gway_remote/maintenance_fence_contract.py` and hermetic tests. It is **not a lock**. No runtime or deployment path imports this module. No SQLite, journal, disk state, GitHub calls, scheduler changes, system services, privileges, node access or Ansible integration are provided.

## Intent and trust boundary

`Claim` binds node/repo/40-digit SHA, an independently derived 24-digit lowercase hexadecimal principal, source (manual/agentops/schedule/workflow), 32-digit request ID, boot ID, strictly positive generation, deterministic SHA-256 correlation token and lease deadline in nanoseconds. `Receipt` holds the event, state, generation, request ID and SHA-256 digest of a canonical versioned payload. All schema fields are validated strictly; bool is not an integer. No secret is stored in a token.

The token is an unkeyed **digest, not a capability or proof of authority**. Neither the principal nor the boot ID is authenticated here. `verified_principal` and `verified_admin` must be supplied from independently authenticated authorities by a *future, separately approved* integration. Caller-provided monotonic nanoseconds and boot ID are not verified. The algorithm does not guard against replay across processes, forged digests, wall-clock jumps, journal corruption or concurrency. Never treat the pure state as a deployment permission or evidence of exclusive ownership.

## Pure state transitions

- `idle → held`: first generation=1 acquisition with live lease, returning an immutable receipt.
- `held → held`: exact duplicate acquisition returns the same state/receipt. Renewal requires the identical claim and a strictly larger deadline.
- `held → uncertain`: competing claim/race, stale generation, stale lease, expiration, explicit fault/crash report or changed observed boot ID. New acquisition cannot clear uncertainty.
- `held → terminal`: successful completion while the exact claim is current and unexpired.
- `uncertain → terminal`: only explicit `recover` with independently verified administrative identity, exact prior generation and digest, and strictly larger generation; the result is a **terminal tombstone**, not an unlocked resource.
- `terminal → terminal`: immutable; no automatic reacquisition. A future implementation would require externally proven quiescence, durable state and a separate new epoch protocol.

Invalid schemas raise sanitized `FenceError` without side effects; they are *not* converted into permission to proceed. Any conflicting valid claim during `held` yields `uncertain`. This is conservative local reasoning, not a linearizable compare-and-swap. The `Fence` object is immutable but callers may hold divergent snapshots and simultaneously believe that each one acquired it. A reconstructed or compromised snapshot cannot be trusted.

## Adversarial acceptance and limits

Run the offline tests via `python -m unittest tests.core.test_maintenance_fence_contract -v` (or `python -m unittest discover -s tests/core -p 'test_maintenance_fence_contract.py'`). Tests cover exact duplicates, simulated competing acquisitions, stale tokens/generations, expiry and boot change, monotonic renewals, crash/fault uncertainty, corrupted receipts/schema, invalid principal and manual recovery tombstones. They do **not** demonstrate real interprocess exclusion, crash durability, admin authorization, clock provenance, reboot fencing or race-free deployment.

Before any operational stage, independently design and approve: one durable owner and arbitration mechanism shared by schedule/manual/AgentOps/CLI/MCP, authenticated identity, crash-safe journal and fsync, lease-clock provenance across reboots, fencing at every side-effect boundary, real quiescence checks, receipts tied to actual effects, recovery protocol, and reversible schedule suspension. GitHub `concurrency` and simulator `flock` alone do not cover all routes. No such stage is authorized here.

## Rollback

Revert only this standalone module, its offline tests and this document. There are no migrations, runtime toggles, deployed binaries or state to roll back. Keep #561 open.
