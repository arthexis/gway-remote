# #565 P3-F1 — optional checked snapshot in pure reconcile policy

`reconcile.reconcile(targets, now, *, catalog_targets=None)` now
accepts an **optional caller-supplied, immutable ordered tuple**
of `(name, repository)` entries. No consumer is changed in P3-F1.

The optional tuple must be **exactly** `reconcile.TARGETS`, with its
existing seven IDs, repository associations, and order. List/dict,
tuple subclasses, omissions, duplicates, reorderings, changed URLs
and simulator additions return a `BLOCKED` plan with no pending
or desired revisions, no quiet deadline, and a stable drift reason.
The validation happens before inspecting target states and after the
existing timezone check. The default `catalog_targets=None` path
retains byte-for-byte equivalent behavior, including reasons,
quiet-period decisions, output ordering and CI/installed-SHA guards.

The pure policy performs no catalog loading, GitHub calls, process
execution, filesystem reads or persistence. The reviewed
`reconcile.TARGETS` **remains** an independent trust boundary for
`catalog_shadow.check_shadow_parity()`; descriptive catalog data
does not grant authority to deploy.

Scope: `gway_remote/reconcile.py`, hermetic policy tests, and
this document only. In particular, no change to callers,
`appliance_watch`, journal reservations, `attempt_policy`,
`deploy_dispatch`, root-owned inventory, installers,
Ansible, provider manifests, workflow YAML, credentials or nodes.

Rollback: revert these three files. Keep issue #565 open.
Future caller integration requires a separately reviewed increment.
