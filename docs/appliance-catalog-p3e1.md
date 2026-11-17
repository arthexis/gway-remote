# #565 P3-E1 — checked source metadata in the appliance watcher

Only `appliance_watch.check()` changes its read-side
`name -> GitHub repository` map from the legacy
`reconcile.TARGETS` to one strictly validated
`catalog_shadow.load_catalog()` snapshot.
It validates **before** reading credentials, attempt journal,
reservation journal, inventory, diagnostics, GitHub or any issue/dispatch
operation. A missing, malformed, duplicated or drifting catalog raises
before side effects, without fallback.

The reviewed seven mappings and order remain byte-identical by
`check_shadow_parity`; no newly visible repository receives execution
rights. All deployment admission remains defined by the separate
root-owned inventory, `deploy_dispatch`, actor/node workflow
allowlists, handlers, and the existing watcher eligibility logic.

This migration intentionally leaves `_dispatch_reservations()` and
`_reserve_dispatch()` using the previous registry. Their journal
authority, SHA validation, write-before-dispatch, deduplication,
serialization, `_busy()`, locks, and `apply` behavior are unchanged.
The watcher does not grant deployment by reading the catalog.

Hermetic tests use only fake inventory/diagnostics/GitHub responses
and mocks; cover read-only/managed/unmanaged, reserved, busy,
failed CI, unknown revision, issue routing and invalid catalog
preflight. No real dispatch, issues, network, credentials,
processes, nodes or installed data are touched.

Rollback: revert these three code/test/documentation files.
Keep #565 open for separate acceptance of operational reservations.
