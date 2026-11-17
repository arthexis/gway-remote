# P3-B1 — checked catalog enumeration in status (#565)

**Draft-only, read-only data-consumer migration.** Only component enumeration
inside gway_remote/status.py changes. All seven names remain in their
original order. The independently reviewed probes, installer code, policy,
release evidence and existing status formatter remain unchanged.

## Call graph and validation boundary

Before:

    status() -> reconcile.TARGETS -> unchanged probes and evidence

P3-B1:

    status()
      -> exactly one catalog_shadow.load_catalog() snapshot
         -> load_catalog_data(): strict packaged P1 JSON
         -> check_shadow_parity(): ordered reconcile.TARGETS,
            INSTALLERS, PROBES and callable adapter existence
      -> tuple(target.id for target in catalog.targets)
      -> unchanged probes and evidence

The loader is imported but **not invoked at module import time**. It
runs inside status(), after the depth argument guard and before journal
or probe I/O. Invalid, missing or duplicated metadata and reviewed
adapter/probe drift raise ValueError with **no fallback** to the legacy
registry. An inconclusive runtime probe, invalid journal or missing
independently observed installed SHA continues to mean **unknown**.

The JSON metadata cannot provide executables, host names, credentials,
installed-revision proof, runtime-health authority or deployment
permission. The root-owned node inventory remains separate. There
are seven P1 known repositories, but only six admitted by the existing
Appliance Deploy workflow. Reports remains excluded pending independent
PR #564; Simulator is never admitted. Bastion remains stage_only;
a staged SHA does not prove activation or runtime health.

## Exact public compatibility

- Preserve status schema gway-remote/status/v1, quick/deep behavior,
  target order, attempted vs installed SHA, health, timestamps,
  activated_at, release_state, staged_sha, deployment_evidence, power,
  watchdog and text formatting. No changes to installed_revision(),
  activated_timestamp(), kiosk_activation_evidence() or any probe.
- Preserve target_export schema=1, the historical ordered seven entries,
  exact canonical JSON bytes and SHA-1 content fingerprint
  f602ee0234e4232246c67aa8cd02bd52fc4bff8b. This is not a signature
  or permission grant.
- Hermetic tests compare the **entire** legacy-order and catalog-order
  status snapshots under deterministic evidence for deep and quick
  modes (including timestamps and nested evidence); prove the one-load
  contract and equal probe call counts; verify failed/started/installed
  attempts cannot become verified installed revisions; and cover
  Bastion stage-only behavior.
- Negative cases cover missing package resource, corrupt and duplicated
  JSON, adapter/probe and stage mode drift, rejection before journal or
  runtime probes, and invalid depth.
- Package tests copy source to an isolated directory and zipapp outside
  checkout. Multiple import orders must not load catalog at import time
  or form cycles. No real node contact, subprocess installation or
  output writes are allowed during status snapshot tests.
- Existing core, deployment, mobile and P2 generator CI remains green.

## Reversal, non-goals and dependencies

A code-only revert restores the original iteration over
reconcile.TARGETS. No SQLite, inventory, installed-release, schema,
workflow or service rollback is required. The old and new deterministic
snapshots must be identical.

Do NOT modify reconcile, best_effort, probe_registry, deployment_evidence,
deployments, diagnostics, report_bundle, retention_preview, mobile,
dispatch/follow, CLI, P2 generator, scheduler/watchers, MCP,
workflows, permissions, locks, Ansible, inventories or any node.
P3-B2/B3/B4 require independent authorization. PR #564 stays Draft.
Keep issue #565 open; P3-B1 remains Draft until separate acceptance,
and only automatic PR CI may be observed.
