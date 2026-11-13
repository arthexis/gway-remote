# P3-A — pure appliance catalog resource load and checked v1 export (#565)

**Scope:** first, strictly read-only P3 consumer migration. This increment
does not replace `reconcile.TARGETS`, add dispatchable targets, modify any
runtime deployment workflow, switch probes/installers, or authorize a host.

## Boundary and call graph

```text
gway_remote.target_export.export_targets()
    -> catalog_shadow.load_catalog_data()
         -> importlib.resources.files("gway_remote") / data/appliance-targets.v1.json
         -> parse_catalog(): closed schema, exact properties, duplicate-key rejection,
            unique IDs/repos/jobs, permitted modes, Bastion stage_only/no probe
    -> catalog_shadow.check_shadow_parity()
         -> reconcile.TARGETS: ordered seven entries
         -> best_effort.INSTALLERS: exact reviewed adapter names/order
         -> probe_registry.PROBES: exact probe IDs and supported kinds
         -> __main__: callable reviewed adapter handles, never invoked
    -> projected {"name": id, "repository": repository}
    -> previous canonical json.dumps(sort_keys=True, separators=(',', ':'))
    -> previous SHA-1 fingerprint (content revision, not authentication)
```

`load_catalog_data()` imports **none** of the above registries and cannot
authorize deployment: it only reads the pinned, packaged P1 resource and
parses strictly. It never fetches from GitHub, writes files or executes
adapters. The legacy `load_catalog()` entry point retains the exact previous
checked behavior by composing `check_shadow_parity(load_catalog_data())`.
The existing P2 static generator keeps using `load_catalog()` unchanged.
Export consumers continue calling `export_targets()` unchanged.

The public `target_export` module now imports the metadata-only catalog
module instead of `reconcile` at import time; the registry checks occur only
during **function execution**, after the pure resource loader returns.
A missing resource, invalid/duplicate JSON, mismatched registry order, wrong
adapter/probe, missing handler or unrecognized release mode fails closed
without falling back to the old list or populating an incomplete export.
The old `reconcile.TARGETS` remains an independent parity witness until
later, separately accepted P3 stages.

## Strict compatibility gates

- `export_targets()` always returns the old 3-key schema:
  `schema=1`, `revision`, `targets`; seven ordered target rows with only
  `name` and `repository`, and canonical JSON bytes unchanged.
- Exact legacy fingerprint is
  `f602ee0234e4232246c67aa8cd02bd52fc4bff8b`. This is a content hash,
  **not** an authorization token.
- Tests compare a frozen byte-for-byte golden export against both the
  pure-catalog-derived export and an independent legacy formatter, then run
  read-only import-order checks in fresh Python processes and in a zipapp
  outside the checkout. The zipapp test copies only code/package assets
  into a disposable directory.
- A missing or invalid catalog makes `export_targets()` raise `ValueError`.
  This is intentional new **fail-closed** behavior; old metadata is never
  silently substituted. On a healthy packaged installation the public bytes
  and CLI `deploy-targets` output stay unchanged.
- Mutating `best_effort.INSTALLERS`, `probe_registry.PROBES`,
  `reconcile.TARGETS`, and syntactically valid adapter/probe IDs must be
  rejected by export parity before output. No handler or subprocess is run.
- The P1 shadow test that previously asserted no active caller is updated
  narrowly: only `target_export` may now import the catalog.
  No CLI, watcher, scheduler, mobile, installer or dispatch module is migrated.

## Explicitly out of scope

`known` != `dispatchable`. The P1 JSON lists all **seven** known targets,
including `ocpp-reports`; the P2 Appliance Deploy workflow continues to
authorize only **six** targets. The independent PR Draft #564 controls any
addition of Reports to GitHub Actions and must be accepted separately.
Bastion is always `stage_only` metadata; staging does not prove activation,
installed revision or runtime health. Approved hosts remain controlled by
root-owned `/etc/gway-remote/deployment.yml` (independent Ansible inventory).
MCP federation and manual provider deployments remain governed by
node-owned, root-provisioned manifests and their execute-scope checks.
Neither can be authorized by catalog metadata.

Do not touch scheduler/watchers, Android/Mobile choices, reconciliation,
status/diagnostics, probe definitions, `best_effort` installers, workflow
DAG, P2 generator, permissions, tokens, locks, installed releases,
service state or report schema in P3-A. Their migration is P3-B/P3-C.

## Reversion and operational safety

A code-only revert of the two loader/export changes and their P3-A
test/doc updates restores the old `target_export` implementation.
`reconcile.TARGETS` and every runtime/authority source remain untouched;
the offline independent legacy formatter produces the exact same JSON bytes.
**No rollback of a deployed release, SQLite, inventory, MCP manifest or
GitHub workflow is necessary for reverting the metadata reader.**

A later squash merge into main would trigger the **existing** automatic
`deploy-backend.yml` workflow; that deployment is explicitly outside this
Draft PR. Observe only PR CI automatically generated by the Draft.
No workflows, Ansible, nodes, AgentOps, MCP or deploy actions are invoked.

Keep issue #565 open for P3-B and P3-C. Do not mark this Draft Ready
or merge without a separately authorized acceptance.
