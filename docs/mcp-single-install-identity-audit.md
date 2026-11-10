# #432 — single installer identity: audit and migration gate

Status: **Draft / not accepted**. This document records a read-only source audit. It does
not authorize changing production SSH identities or removing existing confinement
until a replacement with equivalent guarantees is implemented and tested.

## Required invariant

The user invoking the installer is the sole user for GWay Remote's runtime,
SSH protocol, and MCP/MSP tools. The name is discovered at installation time,
not hard-coded, defaulted, or supplied by an MCP request. MCP tools cannot
override it through `user`, `username`, `run_as`, `become_user`,
`remote_user`, or an equivalent field. A trusted installer must reject an
inconsistent already-provisioned identity rather than silently switching it.

Root-only Ansible installation steps are distinct from the nonprivileged
application runtime; no MCP operation gains a root execution path.

## Verified deviations in main a2cc7ef

1. `deploy.sh` already passes `gway_remote_runner_user=$(id -un)`, but
   `ansible/roles/gway_remote/defaults/main.yml` still defaults it to
   `arthe`. Direct Ansible runs therefore bypass the installer identity.
2. The same defaults set `gway_remote_exec_user=gway-exec` and default
   `gway_remote_exec_run_user` to that account.
   `node-exec-select.yml` explicitly permits either that account or the
   runner; it writes `executor-identity.json` and rewrites the forced-command
   SSH and sudoers target. It also contains `arthe`-specific storage.
3. `node_exec_identity.py` hard-codes `DEFAULT_USER=gway-exec`,
   `OPERATOR_USER=arthe`, a single permitted operator node, home and
   SSH-agent paths. Missing policy silently chooses `gway-exec`.
   `node_exec_worker.require_account()` relies on this selection.
4. `node_exec_protocol.py` uses `sudo -n -u gway-exec` for `file_read`;
   `node_file_reader.py` also requires that hard-coded account.
5. `watchtower_exec_service.load_service()` requires `remote_user` in
   the trusted Watchtower execution JSON. `watchtower_exec_transport.PinnedNode`
   stores it, and `SSHTransport.invoke()` passes `ssh -l remote_user`.
   This field is **not** exposed in the MCP tool payload, but is still
   configurable through a separate root-owned file and violates the requested
   single-identity contract.
6. `node-exec-relay.yml` provisions a distinct `gway-relay` SSH login
   and uses sudo to transition to a selected executor. This is a **second
   Unix account in the transport path**, even though SSH is forced-command,
   host-key-pinned and noninteractive. Simply deleting `-u` or
   `remote_user` without migrating the forced-command login and pinned
   host authentication would break node operations or weaken isolation.
7. `ansible/playbook.yml` uses `become: true` for privileged installation.
   `gway-remote-watch.service` is templated to run as the runner user;
   this is already aligned when invoked through `deploy.sh`.

## Implementation acceptance gates

- Bind installer identity to the trusted SSH login and the actual service
  effective UID, without MCP-selectable usernames. The trusted installer
  must validate continuity against any existing account, state directories,
  keys, authorized_keys, forced-command, and systemd units before migration.
- Remove `remote_user` from Watchtower's persisted execution schema and
  `PinnedNode`; never substitute a constant. Derive the SSH login from
  the trusted installation context, not from MCP data. Reject legacy
  conflicting values rather than silently ignoring them.
- Remove `gway-exec` and `gway-relay` transitions only after designing
  a same-user, forced-command SSH boundary that retains the existing
  pinned host key, fixed protocol, no PTY/forwarding, no shell, request
  identity binding, and least-privilege file read restrictions.
- Preserve existing ledger/job ownership, systemd user-bus readiness,
  cancellation, replay protection, and rollback on failure.
- Negative tests: explicit user selectors at every MCP boundary; missing
  installer identity; conflicting installed UID; unsafe SSH login;
  arbitrary SSH command; identity migration with active jobs; denied
  file access; rollback of SSH/sudoers/identity bytes; idempotence.
- Validate full CI and separately authorized staging E2E before any merge
  or deployment. No node execution, production modification, grant or
  credential changes are authorized by this audit.

## Current decision

**Blocked for runtime changes:** the present transport's login is
`gway-relay` and its forced command crosses to a selected user. Removing
that transition in isolation would invalidate the SSH security boundary.
The migration must be an atomic, reviewed change across installer,
systemd, SSH/forced-command, worker, file reader, transport and tests.
Until then, this Draft is an audit artifact, not an implementation or
an assertion of single-user compliance.

## Additional implementation blockers confirmed in the source review

- `node-exec-prepare.yml` creates a dedicated locked `gway-exec` user,
  private job storage, lingering user manager, and a polkit denial rule
  specifically for that account. Replacing it with the installer account
  without an alternative confinement policy would remove that denial and
  alter the security properties of jobs. Do not apply that polkit denial
  indiscriminately to the installer account: the operator may need polkit
  for legitimate interactive operations.
- `tests/deployment/test_exec_relay_policy.py` currently **requires** the
  `gway-relay ALL=(executor)` sudoers rule and tests its consistency with
  the SSH forced command. `tests/infrastructure/test_node_file_reader_isolation.py`
  **requires** `sudo -u gway-exec`; `tests/core/test_exec_identity_policy.py`
  explicitly expects the `gway-exec` default and `arthe`-only pilot.
  These are not evidence that the policy is correct: they are legacy tests
  that must be replaced with stronger same-UID negative tests.
- `node_exec_worker.py` uses `systemd-run --user`, a user-owned SQLite
  ledger, and a per-user runtime directory. Migration must prove that
  existing in-flight jobs are drained and the durable ledger is preserved
  or safely rejected, without assuming a fixed username/home directory.
- `node_exec_identity.py` currently uses an operator-specific SSH agent
  socket and executable PATH. Replacing this with inherited environment
  would be unsafe: preserve a bounded PATH and validate any agent socket
  ownership/mode against the actual effective UID.

**CI evidence:** baseline Draft #545 documentation-only HEAD
`4519db374d2c3af7191696f7f701a9e1aea076bc`, workflow
`42854616209`, completed SUCCESS 11/11. This is a baseline only; it
cannot establish that the requested identity migration works.

**Safe implementation order:** first add a fail-closed same-UID contract
with isolated tests and a dry-run migration validator, then migrate the
SSH forced-command/transport together with the worker and reader, and
only then remove the legacy identity provisioning. Never deploy an
intermediate state that silently broadens file access or bypasses SSH
pinning. No source review establishes a production-safe migration yet.

## Follow-up review: current CI and provisioning coupling

- Workflow `42856957578` for HEAD `add8af9490f5db4895f567e934edaa7c8a075c3c`
  completed **SUCCESS**. This confirms only the current incremental changes.
- `node-exec-prepare.yml` is included unconditionally from the role's
  `main.yml`. It creates a dedicated executor account, changes linger and
  installs an account-specific polkit rule. Simply deleting the file without
  replacing the include and the associated preconditions breaks installation.
- `node-exec-select.yml` is included from the same role and manages
  `executor-identity.json`, the old SSH/sudoers pair, user bus, job drain
  and rollback. `node-exec-relay.yml` is an opt-in recipe for the legacy
  dedicated SSH login. They must be replaced as a single migration.
- The requested same-UID SSH protocol must use a root-controlled
  `Match User`/authorized-key forced command with the **actual installed
  user**, and the Watchtower transport must obtain that SSH login from a
  trusted, attested installation record. There is no safe generic SSH
  `-l` omission if the local Watchtower service user differs from the
  remote installer user. Do not infer the remote user from the Watchtower
  process UID.
- The existing export primitive validates fixed root, filename, symlinks,
  regular-file type and size; running it as the installer UID does **not**
  grant new Unix file privileges. However, any legacy export directory
  owned exclusively by the old executor may become unreadable. Installation
  must detect this explicitly; never silently chmod or chown production.
- Changes in this Draft already remove the extra `sudo -u` transition
  from the installer's fast-path check and `file_read`. They do **not**
  yet remove the legacy identities from provisioning or transport.

**Acceptance remains blocked** until the root-owned installed identity
record, per-node SSH login, forced-command authorized key, same-UID worker,
ledger continuity, Ansible rollback and all negative tests are implemented
and validated together. Do not merge or deploy the current partial state.

## 2026-11-10 — additional offline acceptance on PR #545

**Status remains Draft, not production-accepted.** Head
`732f5e5638dc9de4da382d0ae43b63581896ae45`, CI workflow
`42878863455`: **SUCCESS 12/12**. All real Ansible and OpenSSH tests run only
inside disposable Debian containers; core tests mock the SSH command runner
and `systemd-run`. No real `node_exec`, SSH credential changes, production
deploy or service changes are made.

**Cross-host identity fixture:** `tests/core/test_exec_cross_host_identity_offline.py`
parses a simulated root-owned Watchtower `execute.json` with the production
`load_service` loader, applies the enrolled host-key/address gate, constructs
the pinned SSH login, and feeds the `limits` JSON request through a stub SSH
transport into the node's **real** `require_account`. The node independently
reads a simulated root-owned `executor-identity.json` and resolves the Unix
UID. Correct login/UID succeeds; mismatched Watchtower login, changed node
identity, drifted effective UID, unsafe config mode and untrusted enrollment
binding are rejected. **This is a simulated cross-host boundary, not a live
remote identity attestation**; the Watchtower config does not contain an
independently attested node UID field.

**User bus / limits / crash-safety:** `test_node_exec_offline_runtime.py`
tests the correct user-bus owner, socket type and synthesized environment,
and rejects missing, foreign-owned, writable or nonsocket buses. A fake
`systemd-run` callback verifies the `--user` invocation, unit name and
MemoryMax/TasksMax/RuntimeMaxSec/KillMode restrictions, without starting a
unit or running a command. The SQLite ledger survives simulated restart,
replayed request IDs are not launched again, and a missing user unit
reconciles to `unknown` without reenqueuing. Root-owned
`executor.json` auto/explicit concurrency and invalid/unsafe overrides
are also exercised.

**Preservation under failure:** the disposable Ansible opt-in fixture
checks exact bytes of administrative `authorized_keys`, root-owned node
identity, existing restricted keys and forced-command file before and
after failing opt-in / mismatched policy checks. The legacy Ansible cutover
`block/rescue` fixture injects three faults and compares original
identity, sudoers and SSHD bytes, also asserting unrelated
`authorized_keys` bytes are preserved. This is evidence of
**fail-closed prechecks and legacy compensation**, not an assertion that
the new opt-in has an atomic rollback after a failure *during* key
installation.

**Still required before acceptance:** establish independently trusted
cross-host UID binding on a staged node, a positive actual `systemd --user`
manager and bounded worker lifecycle, and transactional rollback/migration
coverage for the *new* opt-in path including faults after key write. These
need separate explicit staging authorization; do not merge or deploy
PR #545 on this offline evidence alone.

### Dedicated SSH key collision: proven and fixed

A separate disposable Debian/Ansible negative case demonstrated that
`ansible.posix.authorized_key` with `exclusive: false` can still accept an
executor key already present as an **unrestricted administrative key**;
nonexclusive prevents unrelated key removal, but does not guarantee
per-key option preservation. Workflow `42879373860` recorded the
unexpected acceptance of this collision with structured extra-vars.

The opt-in now checks existing `authorized_keys` ownership/type/mode
and performs an immutable, no-follow Python read before any entrypoint
or key mutation. A colliding key is rejected unless it is **already**
authorized with exactly the dedicated
`restrict,command="/usr/local/libexec/gway-remote-exec-protocol-v1"`
option. The positive second-pass idempotence fixture still passes, and
the negative test byte-compares the administrator key file. No private
SSH material is read by the test outside its disposable container.
Final CI for code HEAD `004bf457c48ef37569198eeeb626e22d49168717`,
workflow `42880349980`, completed **SUCCESS**.

This closes the identified key-reuse flaw, but it does not establish
transactional rollback of a partially completed future migration.
