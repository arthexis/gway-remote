# Issue #561 · D0 offline Go ARM64 diagnostic contract

**Status:** draft contract and hermetic unit tests only. This code cannot execute,
authorize, acquire locks, create files, contact nodes, or prove runtime safety.
No entrypoint imports the D0 module; no workflows, CLI, MCP, broker, AgentOps,
Ansible, services, SQLite or releases are changed.

## Scope and source identity

- Remote base: `2de97a6fb889f8e809bc369910f9a62696c832a8`.
- Simulator fixed main: `67e2d0e0fef704d7c693a6bd86af29bcc60db9a5`.
- Intended node and unprivileged user: `gway-001` / `arthe`.
- Workspace: `/tmp/go-diag-<request_id>`, private and disposable.
- Resource declaration (D1-A): the single canonical V1-B tuple
  `("node/gway-001",)`, a **conservative whole-node footprint** that covers
  compute pressure and Simulator-related filesystem/process effects. The old
  `node:gway-001:*` colon syntax is invalid and no longer accepted. The
  fixed plan is not supplied by an untrusted caller. Narrow child keys must
  not replace it until real footprints and external entrypoints are attested.
- Expected steps, strictly ordered: `mod_tidy`, `mod_verify`,
  `build_backend`, `build_uidlab`. The first failure stops all later steps.
- Existing simulator schedule is `*/10 * * * *` and uses GitHub concurrency
  `ocpp-simulator-gway-001-auto-install`. The backend workflow uses a
  **different** group, `gway-001-appliance-report`. GitHub groups are not a
  process-wide mutex or sufficient memory/CPU exclusion.

## Proposed runtime contract (not implemented)

D1 must establish an **independently attested** lock shared by all relevant
schedule, manual, broker and deployment entrypoints. The lock must cover
admission, staging, sandbox execution, and cleanup, including descendants.
A declaration saying `shared_lock_held=true` is NOT evidence that a kernel
lock exists. Unknown owner, reboot, stale epoch, unrelated process, missing
entrypoint, or ambiguous cleanup fails closed. Do not conflate scheduler queue
ordering with physical node quiescence or ResourceFence admission.

D2 may add an executor after separate review of privilege and isolation:

1. Reverify both immutable SHAs, CI and node eligibility at admission and again
   before any side effect. Do not trust a caller-supplied `trusted_resources`.
2. Acquire the shared exclusion barrier **before** creating or writing to
   workspace. Build from a pinned checkout and verified offline module cache.
3. Prove network namespace has no usable host or CSMS connectivity, host file
   system is not writable, host sockets/SSH agents/secrets are absent, and
   execution cannot gain privilege. A `bwrap --unshare-net` argument alone
   is not attestation; test the *effective* namespace and mount setup.
4. For Go ARM64 use bounded, measured resources (design limits: 1024–4096 MiB,
   max two Go compilation workers, 60–1200 seconds). Check actual available
   memory and cgroup limits; a 128 MiB/60 s node_exec execution is insufficient.
5. Run `go mod tidy`, `go mod verify`, build backend, build LAB client, using
   a sandbox-local source/cache, and stop at the first failed terminal step.
   No launch of the simulator, OCPP connection, CSMS/SQLite write or release
   installation. Enforce process-tree kill on timeout.
6. Emit only fixed-schema receipt with result enums, bounded exit codes,
   no argv, paths supplied by commands, environment, stdout/stderr or tokens.
   Verify process reaping and removal of temporary checkout/cache *before*
   claiming success. A crash/uncertain cleanup remains `UNCERTAIN`.
   Safe recovery must inspect owned temporary paths with no symlink following
   and must never delete the operator checkout or simulator releases.

A passing `assess_offline` result means *only* that the pure declarative
contract is internally complete. It is not permission to run Go.

## D1-A canonical resource compatibility (offline only)

`gway_remote.maintenance_fence_resources.plan` defines the sole valid V1-B
resource grammar. D1-A imports this pure planner and its `conflicts` predicate;
it does not acquire any lock, touch journal storage, nor authorize execution.
`DiagnosticPlan.validate` requires exactly `("node/gway-001",)` and verifies
canonical equality with `plan`. `conceptual_conflicts` rejects malformed,
unsorted, duplicate, or ancestor/descendant-redundant input tuples rather than
silently broadening or narrowing external claims.

Examples (pure conflict logic, **not** proof of runtime exclusion):

| Left | Right | V1-B conceptual conflict |
| --- | --- | --- |
| `node/gway-001` | `node/gway-001/deploy/ocpp-simulator` | Yes |
| `node/gway-001` | `node/gway-001/deploy/gway-remote` | Yes |
| `node/gway-001` | `node/gway-001/service/ocpp-csms` | Yes |
| `node/gway-001` | `node/gway-002` | No |
| `node/gway-001/deploy/ocpp-simulator` | `node/gway-001/deploy/gway-remote` | No (unless shared effects are proven and declared) |

Sibling keys may be disjoint under the *pure* algorithm but in practice still
share CPU, memory, cache, systemd and deployment pathways. Consequently D1-A
uses the whole-node key and does not claim operational independence. A boolean
`BarrierEvidence` is still only an untrusted D0 declaration, **never** a
receipt from a coordinator. The D1-B/D1-C coordinator and execution entrypoint
coverage remain separate, unsatisfied prerequisites.

## Relation to MaintenanceFence

V1-A/B planning, V1-C1 SQLite journal and V1-C2 provenance checks are
**offline-only**. No shared runtime authority exists yet. V1-D must
separately establish trusted principal/boot/clock provenance, safe path and
inode lifetime, resource lock ordering, mutual exclusion with
uninstrumented legacy paths, and fencing before each effect. Do not wire
this D0 model directly to the operational journal.

## D1-B1 pure coordinator state model — no runtime authority

`gway_remote/go_diagnostic_coordinator_d1b1.py` is a **pure, immutable
state-transition model** for D1-B1. `reserve(snapshot, binding, witness)`
returns a new snapshot with one canonical V1-B resource-set reservation or
rejects. The entire set is a single value, not partially acquired locks;
**this is not an atomic transaction across independently executing clients**.
Only V1-C1 SQLite `BEGIN IMMEDIATE` supplies atomicity for cooperating
offline clients, and its path-based open remains unfit for runtime authority.

The model calls V1-C2 `validate_claimed_binding` with separate, injected
`Witness` fields, `BootSample`, and canonical `plan` resources. A test-supplied
witness is **not authenticated** by the model; `assess_offline`, `reserve`,
and `Receipt.sanitized` do not return capabilities or execution permission.
`check_order` encodes the global GitHub queue -> node coordinator -> brief
SQLite transaction -> legacy flock -> effect sequence, not an acquired lock.

D1-B1 states: `HELD`, `UNCERTAIN`, and `TERMINAL`. Expired leases, changed
boots, or unverified child reaping/workspace removal move an active claim to
`UNCERTAIN` and preserve overlap blocking. `finish` models ordinary,
clean **offline** completion only; **V1-C1 does not implement this ordinary
terminal transition**, and the model must not be connected to V1-C1 until
the persistence contract is separately reviewed. `recovery_preview` checks
injected admin/quiescence assertions but does **not** recover, free locks or
validate their real-world provenance. Journal capacity at 4096 and generation
overflow reject without pruning, resetting or automatic recovery.

### Deferred runtime proof, not implied by hermetic tests

- No kernel lock, trusted principal/boot/monotonic clock acquisition, IPC,
  process-tree control, GitHub dispatch or Ansible effects
- No FD-anchored SQLite lifetime: V1-C2 audit is point-in-time and V1-C1
  `sqlite3.connect(path)` retains a TOCTOU hazard
- No global linearizability across real callers, no fencing tokens consumed by
  effect destinations, no proof that surviving children are stopped
- External AgentOps and direct manual/legacy entrypoints remain unverified;
  PR Draft #583 inventories paths, but does not certify their completeness

### New hermetic tests

```bash
python -m unittest tests.core.test_go_diagnostic_coordinator_d1b1 -v
```

Tests cover canonical resource conflicts, independent witness mismatch,
replay of changed identities, model snapshot atomicity, disjoint node claims,
stale generations, expiry and boot changes, unknown descendants/cleanup,
crash snapshot preservation, administrative recovery preview, strict
phase order, and the 4096-event boundary.

**Acceptance for D1-B1:** pure model and tests may reach PRE-READY only.
Do not mark PR #584 Ready, merge, deploy, run Go, or close #561.

## Risk/acceptance matrix

| Threat | D0 requirement | Runtime proof deferred to |
| --- | --- | --- |
| Scheduled auto-install races | All entrypoints required in barrier claim | D1 kernel-lock owner and coverage |
| Different workflow concurrency groups | Exact resource scope | D1 all entrypoint audit |
| Access to CSMS | Network isolation flag | D2 effective namespace probe |
| Writes outside /tmp | Private workdir and readonly host requirement | D2 mount/FD audit |
| SSH tokens or leaked stdout | Fixed receipts only | D2 sandbox and output sanitizer |
| OOM or runaway compilation | Bounded memory/parallelism/time | D2 cgroup and process tree test |
| Interrupted cleanup | UNCERTAIN terminal state | D2 crash recovery |
| Mutable main or stale revision | Exact SHAs on plan | D1/D2 independently checked SHAs |

## Offline tests

```bash
python -m unittest tests.core.test_go_diagnostic_contract_d0 -v
```

The tests cover V1-B hierarchy, root/descendant overlap, canonicalization,
conceptually disjoint nodes and siblings, malformed resource claims, invalid
identity/SHA/path/resources, disabled isolation
flags, resource limits and Boolean spoofing, missing scheduler coverage,
invalid state transitions, fabricated success, continued steps after failure,
unverified cleanup and arbitrary unsanitized receipt text.

**PRE-READY limitations:** This does not demonstrate arm64 execution, tool
availability, connectivity isolation, usable Go module cache, liveness of
GitHub runners, or any status of `current`/`previous`. Do not mark Ready,
merge, deploy or close #561 based on offline test success.
