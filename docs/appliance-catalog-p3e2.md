# #565 P3-E2 — checked catalog for watcher reservation journal validation

P3-E2 migrates only the approved journal-name check in
`appliance_watch._dispatch_reservations()` from the duplicate
`reconcile.TARGETS` mapping to the strictly checked
`catalog_shadow.load_catalog()` metadata IDs. The loader enforces
exact ordered parity against the seven reviewed targets, installer
handlers and probe registry; malformed/missing/drifted catalog raises
before journal access, including when the file is absent.

**No new authorization**: repository visibility, catalog membership,
reservation presence and an attempted SHA do not prove that a node
may deploy. Root-owned managed inventory, explicit deployment
workflow/actor/node guards, reviewed installers and installed MCP
provider manifests retain independent authority. Simulator remains
unadmitted.

The journal schema, SHA validation, directory, filename and JSON
format are unchanged. `_reserve_dispatch()` continues to check
reservations, write and `fsync` a temporary file, atomically
`os.replace` before dispatch, and clean up on failure.
`_busy()`, watch cooldown/CI/health logic, `eligible()`,
issue routing and one-request-per-tick stay unmodified. Every
standalone journal read rechecks the catalog, including at the
reserve call, and fails closed on mid-tick drift.

Hermetic tests use temporary journals and mocked dispatch (never
real GitHub or nodes): seven-name parity, absent/drifted catalog,
invalid names and SHA, atomic replace, rollback on replace failure,
the write-before-dispatch ordering, previously-dispatched idempotence,
and unchanged issue/write boundaries. The P3-E1 test which formerly
asserted no catalog load from the journal reader is revised to
assert the new required checked read.

Rollback: revert these four code/test/documentation files.
Keep issue #565 open. No Ready, merge or activation authorized.
