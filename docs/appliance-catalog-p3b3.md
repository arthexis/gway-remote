# #565 P3-B3 — retention preview enumerates checked appliance catalog

**Draft-only read-side increment.** The one legacy `reconcile.TARGETS`
enumeration inside `retention_preview.preview()` now uses one ordered,
strictly validated `load_catalog().targets` snapshot.

The seven approved target names, their order, selected-repository filter,
`gway-remote/retention-preview/v1` report structure, `dry_run=True`,
`deletion_enabled=False`, unknown/unsupported handling, filesystem safety
bounds and all fixed owner-defined release roots remain unchanged.

The catalog is validated before any home/path or release inspection;
malformed, missing, duplicate or drifted packaged metadata fails closed.
No catalog metadata supplies executable paths, authorizes retention deletion,
changes install rights, or adds the simulator as a known appliance target.
Node-owned MCP manifests and root-owned Ansible inventory remain independent.

Hermetic regression tests cover unchanged seven-target ordering, unknown
target rejection, deterministic selected results, a single catalog load,
invalid-catalog rejection before filesystem access, missing release roots,
and no import-time catalog load. Tests do not touch hosts or installations.
Retain the previous tests and run only automatically triggered PR CI.

**Rollback:** revert these three files; no schema, inventory, installed
revision, release path, scheduler, CI, node or authorization migration.
Keep #565 open; no Ready, merge, node operation or deployment.
