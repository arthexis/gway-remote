# Maintenance lock V1 — shared host-local installation exclusion

Status: **documentation-only proposal; no runtime consumer or deployment authority**.

This contract replaces the proposed MaintenanceFence coordination *architecture* with one
cooperative, host-local Linux `flock`. It does not replace existing deployment
authorization, checked main SHA/CI, owner identity, service health, immutable
releases, retention rules, receipts, rollback, or SSH/OAuth boundaries. The
contract is intentionally independent of a hostname, node ID, repository, and
any specific Ansible layout. Implementations are repository-owned, not required
to import GWay Remote.

## Scope and identity

- A host has one canonical lock pathname for its **installation operator**:
  `~/.local/state/maintenance.lock`, where `~` is resolved from the
  authenticated **effective UID** via the OS account database, not an
  untrusted `HOME` environment variable. No `gway-001` suffix, repository
  suffix, network lock, SQLite database, lease, or fencing generation.
- A single lock covers one installation transaction on that host: admission
  rechecks, staging, side effects, activation, verification, and any rollback.
  Read-only discovery and hermetic tests need not acquire it. Release pruning
  or other maintenance that mutates overlapping installation state does.
- All cooperating entrypoints affecting the same installation state must
  execute under the **same non-root installation UID** and lock inode on that
  host. Ansible `become` is permitted for individual approved tasks; it must
  not silently move the supervising lock owner to root or another account.
  If actual entrypoints use incompatible UIDs or shared homes, do not assume
  exclusion: reconcile their installation identity before enabling the rule.
- Separate physical hosts have separate locks even when their operator
  usernames and relative paths match. A lock acquired on an orchestration
  host is **not** proof of a lock on a remote execution host.

## Secure file and lock lifetime

1. Verify each relevant home/state directory is trustworthy, with no
   untrusted symlink or writable path substitution, and a private
   operator-owned state directory. Create the lock inode only in that
   trusted directory with restrictive permissions (`0600`).
2. Open using `O_NOFOLLOW|O_CLOEXEC` (with create/read-write flags as
   needed). Confirm `fstat` reports a regular file, the intended UID,
   restrictive permissions and no unexpected hardlink aliases; compare its
   device/inode to a no-follow lookup through the held directory descriptor.
   Revalidate after acquisition, before the first installation effect.
3. Acquire **exclusive `flock`** with a bounded wait. A failed acquisition
   must produce `BUSY` without starting any installation effect.
4. Preserve the same **open file description** over the protected operation.
   Never unlink, rename, truncate, replace or recreate the lock pathname
   to "unlock." An unused lock file may safely remain on disk.
5. Close the lock-holding descriptions only after successful completion,
   verified termination, or verified cleanup. A lock is kernel-managed:
   file existence is not lock ownership. No heartbeat, age-based unlock or
   automatic lease expiration is allowed.

A descriptor's number or matching inode alone **does not prove** that the
caller holds an exclusive lock. An untrusted environment flag such as
`MAINTENANCE_LOCK_HELD=1` is not an authorization. An implementation must
make the supervising trusted entrypoint the owner of the acquisition and
preserve the verified open file description into its supervised descendants
where required. It must not attempt a second independent `flock` in a nested
installer, which could deadlock. If trusted descriptor inheritance / ownership
cannot be established, fail closed before installation.

## One acquisition across nested entrypoints

The supported operations are (a) a direct installer that acquires this lock,
or (b) a trusted orchestrator that acquires it exactly once and invokes its
installer as part of the same supervised transaction. Implementation-specific
descriptor handoff must be explicit and verifiable; do not rely on mere
environment claims, shell arguments, or a pathname existence test. Preserve
installed authorization, pinned SHA and CI policy independently.

A deployment *batch* must define whether its deadline applies to the whole
batch or to each separately admitted installation. A new per-component
deadline or lock acquire must not silently bypass a transaction-wide budget.
No consumer is activated by this document.

## Deadline and process supervision

- The normal engineering target is **180 seconds** for a verified installation.
- The **absolute transaction deadline is 300 seconds** from the monotonic
  start of the request, inclusive of lock wait (maximum **20 seconds**),
  preparation, Ansible, activation, health verification, rollback where
  applicable, and process cleanup. No nested command resets the deadline.
- The supervisor should request **SIGTERM near second 275** and escalate to
  **SIGKILL near second 290**, leaving time to observe termination and write
  a sanitized receipt by second 300. These are initial reviewable budgets,
  not permission to exceed the absolute deadline.
- Prefer a dedicated systemd-managed cgroup/scope for the installation
  transaction, with stop/kill coverage of temporary child processes.
  A process group is acceptable only when descendant escape and detached
  subprocesses are ruled out by tests and the real execution model. Merely
  passing `timeout=300` to `subprocess.run`, or terminating just its leader,
  is insufficient.
- Deliberately enabled long-running application services must not be killed
  as though they were transient installer children. Their health and
  activation outcome must instead be verified within the budget.
- Remote SSH or TV effects require an independently trustworthy completion
  or cancellation observation. Terminating a local SSH client does not
  demonstrate that the remote installation stopped.
- After interrupted activation, do not assert release health or silently
  repeat installation. Existing rollback/fail-forward contracts govern the
  artifacts left by a failed or interrupted installer.

**The hard five-minute limit is a limit on installation execution, not an
instruction to release exclusion while uncontrolled effects continue.**
When the operation's quiescence cannot be established, report `UNCERTAIN`
and do not fabricate a clean release or force-unlock. The kernel may release
`flock` upon process exit even when untracked effects remain; the uncertainty
gate below is therefore a separate minimal safeguard.

## Terminal results and uncertain gate

The following are proposed public semantics for future adopting installers,
not newly implemented CLI behavior:

| State | Suggested exit code | Required meaning |
| --- | ---: | --- |
| `SUCCESS` | `0` | Installation completed and independent verification passed |
| `FAILED` | `1` | Known failure; no verified success |
| `INVALID` | `2` | Unsafe configuration, identity, path or admission |
| `BUSY` | `3` | Lock not acquired within at most 20 seconds; no install effects |
| `TIMEOUT` | `124` | Deadline reached and transient activity proven terminated |
| `UNCERTAIN` | `125` | Process or remote effects cannot be proven quiescent |

- Before releasing a verified lock on an **uncertain** termination path,
  atomically persist a minimal, operator-owned, private marker at
  `~/.local/state/maintenance.uncertain` with no secrets: schema version,
  bounded operation/request reference, start/end monotonic observations where
  meaningful, and sanitized reason. Use durable write/rename and sync as
  required to avoid a falsely absent marker after an abrupt interruption.
  Also account for ungraceful supervisor death: startup/re-admission must
  fail closed when a prior terminal receipt or process lifetime cannot be
  independently established.
- This marker is **not** a replacement lock, SQLite journal, lease or claim
  database. It never expires automatically; it is an exceptional safety
  barrier for admission. Future automated installations must refuse to begin
  when it exists until authorized operational inspection establishes
  quiescence and explicitly clears the incident.
- If marker persistence fails while quiescence is unknown, fail closed and
  retain the lock where possible; never report `TIMEOUT` or `SUCCESS`.
  Abrupt kernel death, reboot and orphaned remote effects require separate
  conservative admission handling: `flock` alone cannot prove quiescence.
- A `BUSY` result must not consume a one-shot deployment-attempt receipt or
  be reclassified as an installation failure. **No automatic retry after
  `TIMEOUT` or `UNCERTAIN`**. Existing request-ID idempotency remains intact.
- Keep receipts sanitized and distinguish accepted, started, staged,
  activated, verified and uncertain states. A successful CI run or Git
  checkout is not runtime health evidence.

## Adoption and compatibility gates

Before any installer is migrated, inventory its real entrypoints (canonical
`deploy.sh`, direct Ansible, Python or Bash helpers, provider broker, GitHub
Actions, timers, manual CLI, pruning and remote executor), its host/UID, and
its first/last effect. Confirm all conflicting entrypoints cooperate on the
same lock inode; preserve unrelated idempotency/receipt locks as needed.

Specifically audit nested `appliance.lock`, repository `deploy.lock`,
provider `.managed-provider.lock`, independent scheduling concurrency
groups and direct helper scripts. Do not blindly rename an inner lock to
`maintenance.lock` if an outer layer already holds it. Existing owner and
security policies remain independent.

Before enforcing 300 seconds, measure and optimize actual installation
durations: at least one observed Reports deployment exceeded five minutes.
No production or node rollout, installer change, new service, scheduling
change, or removal of MaintenanceFence contracts is authorized by this
documentation increment.

## Required hermetic tests for a later implementation

- Competing repositories on the same host/inode: exactly one admitted; the
  other exits `BUSY` without side effects. Different hosts do not share
  a lock.
- Symlink, hardlink/path-alias, untrusted parent directory, owner or mode
  mismatch, replaced inode between preflight and acquisition: fail closed.
- Nested orchestrator + installer: one verified acquisition; forged
  environment flag or unrelated FD does not bypass it; no self-deadlock.
- Monotonic budget: 20-second maximum wait, target 180, total 300 including
  cleanup; nested playbook cannot restart the clock.
- Normal completion, crash, SIGTERM/SIGKILL, child escape, detached session,
  uninterruptible process, unverified remote side effect and reboot:
  truthfully distinguish `TIMEOUT` from `UNCERTAIN`.
- Existing immutable releases, rollback, service health, request-ID
  idempotency and sanitized receipts remain unchanged.
- No automatic retry of uncertain/timeout outcomes; no false installation
  attempt receipt on `BUSY`. No tests may operate on actual node services.

This document is a proposed cross-repository behavioral specification.
Passing offline contract tests does not constitute node-runtime certification.
