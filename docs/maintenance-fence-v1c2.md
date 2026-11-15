# MaintenanceFence V1-C2: offline provenance consistency (#561)

V1-A (contract), V1-B (resource planner), and V1-C1 (SQLite journal) are
already in main. This stage adds **pure/offline** verifiers and a point-in-time
file-descriptor-anchored storage audit. Nothing imports these modules from
CLI, MCP, worker, workflow, deployment broker, AgentOps or Ansible.

## Authority boundary

- `validate_claimed_binding` checks the submitted immutable request binding
  against **independently** supplied authenticated principal, node, repository,
  commit SHA, source and request ID. It requires an explicit equality check
  between canonicalized **declared_resources** and separately verified
  **trusted_resources**; neither is inferred from the other. An omitted,
  expanded or forged resource claim fails closed. It also checks boot identity
  and rejects an expired monotonic deadline. Only a correlation digest is returned: not a permission/token.
- `sample_local_boot` brackets a monotonic-nanosecond observation with two
  boot ID readings. Both readers are supplied by a trusted caller, not by
  serialized request arguments. A reboot, backwards clock, excessive sampling
  delay, invalid type or missing source rejects. This is not a proof that a
  caller used the actual Linux procfs/clock. Observations from distinct
  boots cannot be compared as belonging to one monotonic epoch.
- `validate_recovery_record` verifies metadata against separately derived
  administrator identity, node, **request_id**, exact positive **generation**,
  exact current receipt digest and evidence digest. Stale/mismatched request
  and generation fail closed. It **does not validate** administrative
  authorization or physical quiescence, nor call the SQLite recover method.
  A matching digest of an assertion is not evidence that a worker stopped.
  Binding metadata to a generation does not establish freshness of that
  generation unless the trusted witness is itself independently current.
- Untrusted request dictionaries, federated auth context dictionaries, or
  any user-controlled fields must **never** be reused as their own
  `trusted_*` witness. Even a well-formed FederatedAuthContextV1 requires
  external verification of the bearer/peer and the execution route.

## Storage inspection, not operational opening

`audit_private_sqlite(absolute_directory, filename)` traverses path
components using `dir_fd` and `O_DIRECTORY | O_NOFOLLOW`, requires owner-only
storage directory and owner-only regular DB/`-wal`/`-shm` files, rejects
hardlinks and checks each opened file inode against an anchored `stat`.
Root-owned sticky ancestors such as `/tmp` are allowed **only for offline
tests**; the final storage directory must be private and owned by effective
UID. Missing sidecars are acceptable, a missing database is not.

This is a **point-in-time audit, not a safe SQLite opener**. Closing those
descriptors and later calling `sqlite3.connect(path)` reintroduces a TOCTOU
gap; therefore a passing report cannot be used as execution authorization.
SQLite sidecars may be recreated at runtime; this check provides neither
ongoing sidecar authority nor ownership of external processes. There is no
database creation, mutation, opening via sqlite3, permission repair, or
access to any physical node. A future privileged, inode-anchored design needs
independent review before runtime integration.

## Hermetic tests and rejection posture

`python -m unittest tests.core.test_maintenance_fence_provenance_v1c2 -v`

Tests cover independent principal/node/repo/SHA/request mismatch, declared
versus trusted resource scope, changed boot/expired lease, monotonic clock
rollback, missing boot, sample-time bound, recovery request_id and generation
binding, private DB/WAL/SHM, symlinks, parent symlinks, permissions,
hardlinks, nonregular/missing files, invalid paths and an injected inode
substitution. Rejects are sanitized and fail closed.

V1-C2 does not change V1-C1 journal generation, event replay, leases,
transaction scope or recovery semantics. The 4096-event boundary is unchanged;
an exhausted journal cannot persist a new uncertain event, but never permits
conflicting admission.

## Explicitly deferred V1-D

V1-D needs trusted identity derivation at entrypoints, real kernel boot and
clock provenance, safe path/inode lifetime across SQLite access, physical
quiescence attestation and fencing **before every side effect**, including
GitHub Actions, broker, CLI, AgentOps, Ansible, subprocesses and existing
flock/concurrency mechanisms. No stage here joins those locks or authorizes
Simulator installation.

Keep issue #561 open; R6 unchecked and BeforeAvailable=Quarantined.
PRE-READY concerns **offline contract quality only**, not operational
availability, hardware or power-loss durability.
