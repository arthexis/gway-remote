# MaintenanceFence V1-C1 — offline SQLite journal (#561)

This is an **offline storage prototype**, NOT a deployed mutex, operational fencing
authority, authenticated admission gate, worker monitor, or approval to install
OCPP Simulator. No existing CLI, MCP, AgentOps, workflow, runner, broker or
installer imports this module. V1-A and V1-B are unchanged.

## Model and initialization

`OfflineFenceJournal.initialize(absolute_db_path)` is an **explicit**, create-only
operation in a private (owner-only) directory. It refuses an existing file; a
partially created database is never silently repaired or overwritten.
`OfflineFenceJournal(path)` subsequently opens an existing database in
read-write mode only, using SQLite WAL and `synchronous=FULL`. Database schema
version is fixed at 1; unknown schemas, untrusted permissions, corruption, or
SQLite failures fail closed with a sanitized `StoreError`.

The single SQLite database serializes cooperating callers with
`BEGIN IMMEDIATE`; an atomic transaction persists the entire canonical
resource set, a monotonic generation, an immutable request binding and
the corresponding journal record. Separate resource rows/partial acquisitions
are deliberately not used. Only one active or uncertain claim may overlap any
other in the same journal. Concurrent disjoint resources may coexist.

The request binding contains node, repo, SHA, principal identifier, source,
request_id, boot_id and lease deadline. The caller must independently verify
principal identity and the clock/boot source. No authentication happens here.
`request_id` is globally immutable: exact retries return existing receipt
with no new generation or execution; mismatched bindings/resources fail closed.

## Durable journal and replay integrity

The journal stores monotonically increasing sequence numbers and canonical
JSON snapshots with SHA-256 hash chaining; request materialized rows and
generation metadata are reconciled against **full journal replay** on every
operation. All journal and receipt mutations are committed in one transaction.
A mid-transaction crash cannot leave an accepted partial resource set.
Any missing sequence, unexpected state transition, broken digest, divergent
receipt or counter, malformed path or invalid schema causes a fail-closed error.
The SHA-256 chain detects accidental damage, **not malicious rewrites** by
a party able to alter the database and recompute hashes. Backups, permissions
and independent attestation belong to a later authorized stage.

Supported offline transitions:
- No request -> `held` via `reserve`, generation strictly increasing.
- `held` -> `uncertain` on observed lease expiry or boot change; resources
  remain reserved and new conflicting claims are rejected.
- `uncertain` -> `terminal` via explicit `recover`, expected exact receipt
  digest, externally verified administrator identifier and external quiescence
  evidence digest, with a fresh generation.
- `terminal` never reopens its `request_id`. A different request may be
  accepted after recovery, but only in this non-operational prototype.

A new competing request that detects expiry rolls back its attempted
observation when conflict is rejected; **the conflict stays denied**. An
explicit `observe` or exact duplicate inspection persists the uncertainty.
A fresh record is never admitted merely because a lease expired.

## What is NOT guaranteed

SQLite transaction ordering applies only to processes voluntarily using
**the same database file**. Different files, distributed nodes, GitHub Actions,
`flock`, legacy deployment brokers, subprocesses or privileged services do
not participate. State `held` is **not permission to run**, and the returned
digest is not a fencing capability. A malicious caller can forge identities
and snapshots; supplied `now_ns` and `boot_id` are not authenticated.
A lease does not stop a live process. Recovery accepts external evidence
identifiers **without verifying actual quiescence** and must never be wired
to a real unlock without a separate approval and safety design.

The journal does not infer current runtime or automatically authorize a
deployment. Crash safety does not mean exclusion of uninstrumented work.
No live data migration, deploy, schedule change, disk state on a node, or
system-service modification is included.

## Acceptance and rollback

Run the offline test module:

```sh
python -m unittest tests.core.test_maintenance_fence_store -v
```

Tests use TemporaryDirectory databases, simulate multiple SQLite clients,
stale leases, changed boot IDs, duplicate and conflicting requests,
recovery, mid-transaction rollback, corrupted receipts, journal tampering,
schema damage and invalid paths. This is **not** a real node integration test.

Revert only the offline module, tests and this document. No runtime or
persistent appliance state is introduced by the PR; test databases are
temporary. Keep #561 open, R6 unchecked, and BeforeAvailable=Quarantined.

A later V1-C2/V1-D must prove real authority, clock and principal provenance,
secure journal ownership, lock sharing across all entrypoints, fencing at
side-effect boundaries and reliable quiescence before release.
