# #565 P3-C1 — checked catalog for GitHub state collection

Read-only migration only: `github_state.collect()` now enumerates one
strictly validated `catalog_shadow.load_catalog().targets` snapshot instead
of the legacy `reconcile.TARGETS` tuple. The snapshot is checked before the
first GitHub request; malformed, missing, duplicate or drifted metadata fails
closed without fallback.

Exactly the same seven reviewed repository mappings and ordering are used
for `main_head`, `main_arrival` and `ci_for_head`. The existing
`Candidate` output type, timestamps, CI decisions, failure semantics,
per-target request ordering and `report()` contract do not change.

This does NOT migrate `attempt_policy.plan`, `reconcile.reconcile` or
`appliance_watch.check(apply=True)`; those pure or operational paths need
separate assessment of I/O purity, safe watchers, actor/nodes, concurrency and
root-owned deployment authorization. `load_catalog` verifies reviewed
registries but is NOT node permission, deployment admission or an MCP
provider manifest. No CLI, workflows, Ansible, credential, node or deployment
changes.

Hermetic tests use a fake client and mocked GitHub API adapter methods, cover
byte-stable ordered name/source lookup sequences, attempt association,
fail-closed corrupt catalog before network, unchanged candidate types and
absent import-time metadata load. Automatic PR CI remains the only runner.

Rollback: revert code/tests/docs only. Keep #565 open for independent
acceptance of remaining pure-policy and operational consumers.
