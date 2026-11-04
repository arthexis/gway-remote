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
