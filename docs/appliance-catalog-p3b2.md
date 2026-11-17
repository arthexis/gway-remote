# #565 P3-B2 — checked catalog diagnostic target validation

This Draft migrates **only** diagnostic target membership validation from the
independent legacy `reconcile.TARGETS` registry to the P1/P3-A checked
`load_catalog().targets` snapshot. P3-B1 already migrated status enumeration.

## Contract and failure handling

- The existing seven targets and their report order remain unchanged.
- Validate one catalog snapshot per `diagnose()` before status, logs or
  systemd inspection. Missing, malformed, duplicate or mismatched metadata
  fails closed, without silently using the legacy list.
- Preserve `gway-remote/diagnosis/v1`, unknown/failed classification, log
  sanitization and line bounds, and the caller's directory override.
- Keep the existing `status()`, `read_log()`, `probe_for()`, and
  `_systemd()` code and runtime behavior. No new commands, subprocesses,
  writes, targets, privileges, deployment admission or MCP tools.
- Catalog metadata cannot grant node deployment permission; root-owned
  Ansible inventory and reviewed adapters remain separate.
- Reports remains independently gated by #563/#564; Bastion staged-only
  remains distinct from activated, verified runtime state.

## Hermetic acceptance

Run `python -m unittest tests.core.test_diagnostics_catalog_p3b2` and the
existing `tests.core.test_diagnostics`; full automatic PR CI is authoritative.
Tests verify seven-target order, selected filtering, one catalog snapshot,
negative target rejection and corrupt-catalog failure before observation.
They use mocked reports/logs/systemd and never contact a node.

Rollback: revert only this diagnostic module, tests and documentation;
no runtime migration, schema change, inventory modification or data rollback.
Do not mark Ready/merge or deploy; retain #565 open for further increments.
