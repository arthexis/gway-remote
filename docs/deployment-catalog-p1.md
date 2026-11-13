# Appliance catalog P1 — descriptive shadow only (#565)

Status: **review-only / no active consumer**. This contract follows the accepted
architecture of issue #565. The descriptor is reviewable metadata, **not** a
deployment manifest, node inventory, installer, executable registry or MCP
provider declaration. Never grant execution based solely on this file.

## File and schema

- Package resource: `gway_remote/data/appliance-targets.v1.json`.
- Namespace/version: `"schema": "gway-remote/appliance-catalog/v1"`. This is
  **not** the public `target_export` envelope's numeric `schema: 1`.
- Exact top-level fields: `schema`, `targets`.
- Exactly five fields per target:
  `id`, `repository`, `adapter_id`, `probe_id`, `release_mode`.
- Canonical ordered seven IDs: `ocpp-csms`, `ocpp-reports`,
  `gway-lcd-sound`, `gway-agent-ops`, `gway-ap-kiosk`, `gway-rfid`,
  `gway-bastion`.
- Each `repository` is exactly `arthexis/<id>`. Each `adapter_id` names
  the corresponding trusted `best_effort.INSTALLERS` entry and the callable
  in `gway_remote.__main__`. These IDs are *lookups*, never callable code
  supplied by JSON.
- `probe_id` is the existing `probe_registry.PROBES` key, or `null`
  **only** for Bastion. Bastion lacks a conventional probe and must have
  `release_mode: stage_only`; the other six use `standard`. Missing or
  untrusted evidence stays `unknown`, not `healthy`.
- There is no SHA, desired revision, `enabled`, `approved_nodes`, shell,
  command, path, URL, credential, user, role, permission or workflow content.
  Adding any such property is an error, not a request for a new capability.

`gway_remote.catalog_shadow.load_catalog()` reads a **fixed embedded resource**
through Python 3.10 `importlib.resources`, including when installed from the
archived package or embedded in the CLI zipapp. It does not inspect the working
directory, use subprocess/SSH/network or write state. `parse_catalog(text)`
rejects unrecognized top-level/target fields, missing fields, duplicate JSON
keys (including nested), invalid encodings/values, nonstandard NaN, oversized
payloads, reserved names, malformed IDs and derived job-ID collisions.
`check_shadow_parity(catalog)` then fails on order/identity drift from
`reconcile.TARGETS`, unknown or remapped reviewed adapters, unknown probes,
and Bastion mode mismatch. No fallback turns a corrupt descriptor into a
deployment authorization.

**P1 is intentionally frozen to today's seven known repositories.** Adding a
new type of adapter or changing an existing probe requires separately reviewed
Python code and explicit activation gates in a future phase. Loading a metadata
file never runs an adapter or checks a live host.

## Distinct trust and compatibility boundaries

1. `reconcile.TARGETS` is still the active registry used by the scheduler,
   status, CLI, target export and other consumers. This PR does not import the
   shadow loader in any active path, schedule, watcher or provider.
2. `deploy_dispatch.TARGETS` and the committed static
   `.github/workflows/appliance-deploy.yml` remain independent. Reports is
   **known** in the shadow catalog but **not admitted** to the Appliance Deploy
   workflow on this main revision; issue #563 / Draft PR #564 has its own
   acceptance. There is no Simulator job. Bastion remains stage-only.
3. Hosted workflow admission still verifies the actor/node/selected repository
   and the Ansible inventory. The node's installed
   `/etc/gway-remote/deployment.yml`, provisioned root-owned, remains the
   independent local authority. `odoo-gelectriic` may appear there without
   being a registered Appliance Deploy target. Other nodes remain deny-all.
   A catalog entry neither authorizes a node nor bypasses CI/revision/lock
   checks or the source repository's proprietary `deploy.sh`.
4. Installed root/node-owned `/etc/gway-mcp-providers/*.json`, the MCP
   provider's manifest authority, Watchtower OAuth and agent repository
   policy are separate from this Git metadata. No file here generates them.
5. The public `target_export.export_targets()` still emits
   `{schema: 1, revision: <SHA-1 content fingerprint>, targets: [...]}`.
   A golden byte-for-byte serialization test pins its current data and digest.
   Neither that digest nor this catalog is a signature, an installed release
   revision, proof of healthy runtime or an authorization token.

## Offline acceptance and rollback

`tests/deployment/test_catalog_shadow.py` checks exact ordered identities,
registry binding, immutable/idempotent reads, no commands, duplicate JSON
properties, forbidden privileges/paths, malformed/reserved IDs, job-ID
collisions, incorrect repo/adapter/probe, incorrect release modes, reordering,
registry drift, unavailable resource failure, and the unchanged public export.
It also copies the package to an isolated directory and builds a separate
zipapp containing the embedded resource, then runs both using a subprocess
with a working directory **outside** the checkout and without network.

Future P2 may generate a **static, committed** workflow from reviewed templates,
with a deterministic `--check` and semantic DAG/permission/secret/concurrency
tests. P3 may migrate consumers gradually behind separate acceptance. Neither
action is part of P1. The P2/P3 gate includes audit of backend vs appliance
locks and disparate GitHub Actions concurrency groups, as accepted in #565.

Rollback of this increment means dropping the new JSON, loader, tests and
documentation. Since no live consumer reads them, the active target export,
installer and authorization behavior do not need migration or rollback.
**This does not roll back an installed application or the automatic backend
deployment triggered by any future merge to `main`.** Any merge requires
separate permission and monitoring of the normal push workflow.

P1 must remain a Draft PR until CI and PRE-READY acceptance finish; do not
mark Ready, merge, dispatch, run Ansible or contact nodes in this phase.
