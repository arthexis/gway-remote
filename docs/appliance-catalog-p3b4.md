# #565 P3-B4 — checked appliance catalog in read-only deployment inventory

This Draft migrates the **two read-only uses** of `reconcile.TARGETS` in
`gway_remote/deployments.py` to one checked snapshot of packaged P1/P3-A
catalog metadata inside `inventory()`. No changes to the public
`format_inventory` or the shape or order of `inventory()` rows.

## Authority and compatibility

- Exactly seven reviewed target ID/repository pairs; no simulator admission.
- Fail closed on absent, malformed, duplicate or drifted metadata **before**
  policy selection, GitHub I/O, attempts, installed revision or Bastion reads.
- The only deployment allowance is still the independently obtained
  node inventory `remote_managed_repositories`; metadata NEVER grants rights.
- `deployable` still requires a managed target, an actually local node, and
  `node == "gway-001"`; `gway-004` or remote observations remain nondeployable.
- Preserve GitHub head lookup per selected target, revision comparison,
  independent installed/release evidence, Bastion staged-vs-activated
  distinction, attempt records, timestamps, error semantics and presentation.
- The default Ansible inventory inspection remains a separate fail-closed
  authorization boundary. No new commands, shell, imports with side effects,
  network calls, runtime switches, MCP providers or host access.

## Acceptance and rollback

Hermetic tests cover exact seven-name/repository ordering, managed and
deployable booleans with gway-001 vs gway-004, local vs remote installed
revision evidence, unknown SHA, Bastion staging, invalid selections, missing
policy, catalog failure before any host/policy/network I/O, one snapshot,
and no module-import catalog load. Existing deployment tests and automatic
PR CI must continue to pass.

Rollback: revert three files (inventory code, tests, documentation). No
Ansible, schema, SQLite, installed release, workflow, provider or node
migration. Keep PR Draft and #565 open until independent acceptance.
