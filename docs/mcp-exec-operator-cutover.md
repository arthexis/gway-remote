# GWay Remote M3 executor identity: controlled pilot acceptance

This is the field acceptance for issue #367 and PR #368. It is **not**
a generic authorization to deploy to other machines or change Bastion keys.

## Preconditions

- Merge/deployment is **not** the first acceptance step. Use a reviewed SHA
  from PR #368 with all PR CI checks passing.
- Check that GitHub's main ruleset requires the stable `CI` status before
  allowing main-push-only deployment to replace main-push tests.
- Confirm `gway-001` is attested and reachable. Other nodes retain the
  `gway-exec` default.
- On gway-001 as the existing operator, inspect (read-only):
  `loginctl show-user arthe -p Linger -p State -p RuntimePath`;
  `sudo stat /run/user/1000/bus` (check it is an arthe-owned socket).
  A test performed by `gway-exec` may return false solely because it cannot
  traverse arthe's private runtime directory; do not infer a missing bus from it.
- Verify that the Bastion agent socket exists and is operator-owned. **Never**
  print the key, token, decrypted passphrase or contents of private bundles.
- Check the old executor's durable job database for queued/running jobs using
  `scripts/verify-exec-cutover.py arthe` as root. If any remain, wait for
  completion; do not terminate or replay them to force a cutover.
- The root-run `scripts/verify-exec-relay-policy.py` must confirm that the
  existing SSH forced command and exact sudoers entry agree. Missing relay files
  are permitted only if the bridge was never provisioned.

## Controlled activation

The Ansible role on gway-001 selects `arthe` by explicit node identity;
other gway nodes select `gway-exec`. The role prepares private state,
verifies the user systemd bus and drained old jobs, checks SSH/sudoers agreement,
sets the root-owned identity file, changes the existing exact sudo rule and
ForceCommand, validates the effective configuration, then reloads sshd.
A rescue block restores the prior configuration on task failure.

**Use the existing operator's vetted deployment/Ansible process on the pilot,
not an arbitrary Watchtower-shell command.** Do not modify credentials, SSH
known_hosts or authorized_keys. Observe any failing task and stop; no bypass
of the account, bus or active-job checks is acceptable.

## Live acceptance after deployment

Use the actual GWay Remote execute-scoped MCP connection and bounded job
results, not GitHub mocks:

1. Submit `id -un; hostname`. Expect `arthe` and `gway-001`.
2. Submit `command -v guide; guide where guide` or an existing harmless
   `guide` lookup, and confirm expected operator-visible tools.
3. Submit `test -S /run/bastion-ssh/agent.sock && printf 'present\\n'`.
   Do not inspect the agent's identities.
4. With host identity already pinned by the operator's SSH config, try
   `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5
   ubuntu@gelectriic.com hostname`; repeat for
   `ubuntu@customer.gelectriic.com`. No remote shell configuration changes.
   Both should return an expected host name; log only success/failure.
5. Submit a benign bounded `printf` command, retrieve its result, verify
   request ID deduplication, then verify timeout and cancellation remain
   reliable. Do not repeat a command after an uncertain dispatch.
6. Verify the new private job database is owned by `arthe`, while the
   previous `gway-exec` ledger is preserved and remains private.
7. Check Watchtower's `node_capabilities` and result status. Do not claim the
   execute scope, actual identity or remote reachability based only on source.

## Failure and rollback

The Ansible cutover has a rescue path for task failures, but it does **not**
replace a field rollback drill. If the pilot is unhealthy, keep the
operator SSH path open and apply the reviewed Ansible role with the
`gway_remote_exec_run_user=gway-exec` override on gway-001, after verifying
the `arthe` ledger has no active jobs. Verify the root-owned identity policy,
forced command, sudoers and `node_exec` result are again consistent.
Do not manually chown or delete either account's job ledger. If the rollback
preflight fails, retain the evidence and do not force a second deployment.

Field acceptance requires a recorded deployed SHA, scoped non-secret test
receipts, an observed rollback outcome (or explicit decision to defer it),
and a final operator decision. CI success alone is not field acceptance.


## Minimum gway-001 identity simplification (November 2026, Draft PR)

The normal deployment entrypoint `deploy.sh` invokes Ansible with a transient
local inventory (`-i 'gway_remote,'`) and supplies the actual operator as
`gway_remote_runner_user=$(id -un)`. The persistent
`ansible/inventory/deployment.yml` hostvars are **not** automatically loaded
by that invocation. Accordingly, this change declares
`controller.hosts.gway-001.gway_remote_exec_run_user: arthe` in the canonical
inventory and explicitly loads *only that node's* selection in the existing
role **before** `node-exec-select.yml`. The existing node-local root-owned
identity JSON, SSH ForceCommand, exact sudoers entry, bounded systemd user
worker and SQLite job ledger are still the only runtime mechanisms. The MCP
request never selects an operating-system account.

This is a configuration cutover, **not** a change to OAuth permissions or a
new service. `gway:read` and `gway:execute` keep their distinct enforcement;
Watchtower enrollment and SSH host attestation stay authoritative.
`gway-relay` remains the restricted SSH ingress with forced command,
no PTY and no forwarding. `gway-exec` stays locked and provisioned for
isolated `file_read` and rollback. The existing Deployment Broker inherits
the chosen node executor identity; Ansible still uses `become` for privileged
installation. Other nodes keep the original `gway-exec` default.

### Privilege impact and explicit acceptance gate

**The identity switch increases authority for execute-scoped callers.**
The live operator account `arthe` is a member of `sudo`, can access its
private home and may have access to the Bastion SSH agent. The current
`node_exec` API already accepts bounded shell commands; running them as
`arthe` makes all permissions available to that Unix account reachable
through a valid `gway:execute` authorization. `gway-relay` and the
OAuth token do **not** sandbox commands once they run as `arthe`.
A sudo group membership alone does not establish passwordless root access;
the actual sudo policy and SSH agent permissions must be checked in the
field without printing credentials. The existing runtime explicitly exports
`/run/bastion-ssh/agent.sock` if it passes owner/mode checks; never claim
that an unset `SSH_AUTH_SOCK` eliminates the operator's underlying access.

Before approving a merge or activating production, an operator must
explicitly accept that privilege boundary, confirm no unexpected
passwordless sudo grants, validate the Bastion exposure is intended,
and verify the remaining node execute scope is limited to trusted
operators. If that boundary is unacceptable, **do not deploy** this
identity simplification: retain `gway-exec` and solve provider access with
narrowly scoped exports instead.

### CI and activation checklist

- Offline: run `tests/deployment/test_exec_001_inventory.py`; its Ansible
  fixture executes the **actual set_fact** with disposable inventories.
  Verify `gway-001 -> arthe`, other nodes -> `gway-exec` and
  `-e gway_remote_exec_run_user=gway-exec` remains an explicit rollback
  override. No real SSH, `become`, services or state directories are touched.
- Preserve and run existing tests for `node_exec_identity`, SSH/sudoers
  forced-command negatives and byte-for-byte Ansible rescue, systemd bounded
  workers, SQLite job idempotency/cutover, OAuth negative scopes, federated
  provider authorization and the isolated file reader. These are exercised
  by the repository's PR-only Python checks and Ansible CI jobs.
- **Before field cutover**: verify the installed revision on **both**
  Watchtower and gway-001, the `arthe` user bus as root/operator,
  zero queued/running old jobs, exact existing relay policy, and selected
  provider executable permissions. Do not treat a successful GitHub
  workflow or a Watchtower catalog listing as proof of deployed SHA.
- After a separately approved merge, use only the ordinary automatic
  deployment. Confirm effective `id -un`, root-owned identity policy,
  exact relay sudoers/ForceCommand, worker receipts, provider availability,
  deployment preview, OAuth scope negatives and lack of administrative
  SSH regression before declaring acceptance.
- On failure, invoke the **existing** reviewed Ansible rollback with the
  explicit `gway_remote_exec_run_user=gway-exec` override after checking
  the new ledger for active jobs; do not delete or chown the old ledger,
  issue an ad hoc `sudo -u` execution, or bypass SSH/visudo validation.

As observed during PR preparation, Watchtower's live federated catalog did
not advertise installed providers and the live gway-001 executor was still
`gway-exec`. Those are **pre-cutover observations**, not evidence that the
proposed deployment has succeeded. This Draft PR makes no production changes.
