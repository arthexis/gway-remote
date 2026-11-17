# #565 P3-C2 — pure decision and watcher guardrail characterization

Tests-only increment after P3-C1. This intentionally **does not migrate**
`reconcile.TARGETS` in `attempt_policy.plan`,
`reconcile.reconcile`, `appliance_watch.check` or watcher reservation
validation. Their inputs have different authority and purity contracts from
the read-only P3-A/B/C1 consumers.

## What is pinned

- Exactly seven reviewed metadata names/order; a known repository is not an
  installed or managed repository, nor is it allowed to execute.
- `attempt_policy.plan` is pure: quiet period, CI, no implicit repeat of
  attempted SHAs, full-snapshot/managed subset validation, unknown/duplicate
  rejection and no import-time or runtime catalog/host I/O.
- `reconcile.reconcile` is pure and blocks missing/duplicate targets,
  invalid/unknown revisions or CI, with no false assertion that an attempted
  revision proves an installed or healthy release.
- The watcher does not infer missing installation from unknown revision alone;
  CI, cooldown, attempt and journal reservations guard eligibility.
  Reservation target names and SHA shapes fail closed; tests use temporary
  files and never invoke `check(apply=True)`, GitHub, subprocess or nodes.

## Why a direct migration is not safe yet

Calling `load_catalog()` from a pure policy function adds package
resource I/O and imports handler registries to a path designed to operate on
an explicit immutable snapshot. Replacing the watcher journal allowlist or
issue/CI source mapping also affects an operational dispatch path. Future
migration needs an explicit snapshot ownership contract and proof of no
additional dispatch, no fallback on malformed catalogs, no permission
broadening and unchanged reservation/serialization. Root-owned node
allowlists, independently reviewed installer handlers and installed provider
manifests must remain separate authorities.

No production code, action workflow, runner, policy, inventory, MCP service,
timer, data or node is changed. This is **not** approval to flip the watcher
to apply mode or deploy an appliance. Reversal is deletion of the two new
files; keep #565 open.
