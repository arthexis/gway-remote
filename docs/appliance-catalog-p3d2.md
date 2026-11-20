# #565 P3-D2 — single checked snapshot at the read-only report caller

`github_state.report()` now loads one checked declarative catalog
snapshot and supplies the **same immutable ordered tuple** to
`github_state.collect()` and `attempt_policy.plan()`.
The collector's optional keyword-only input is explicitly checked
against the legacy reviewed seven-target tuple before any GitHub
request. Direct legacy `collect(client, attempts)` calls still load
one checked catalog in the collector.

The pure `attempt_policy.plan()` performs no resource reads or
process/network I/O, and its deny-all, managed subset, missing CI,
cooldown, one-attempt-per-SHA and failure semantics are unchanged.
No unknown or simulator repository is admitted by a descriptor.
The report still has the same four keys, seven ordered rows and
attempt ordering. Missing or inconsistent metadata fails closed
without fallback before network calls.

This is a read/report wiring change only. No change to
`reconcile.reconcile`, `appliance_watch` (including
`apply=True`), dispatch, reservations, locks, workflows,
root-owned node inventory, installer handlers, service manifests,
providers, credentials, Ansible or deployed nodes. The catalog
is **metadata, not authorization**.

Hermetic tests cover single-load and request order,
same-snapshot propagation, output/CI equivalence, direct legacy
collection, malformed/injected inputs and fail-closed behavior.
Rollback is the three changed code/tests/docs files. Keep #565 open.
