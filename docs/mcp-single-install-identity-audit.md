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
