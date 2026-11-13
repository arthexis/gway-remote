# P2 — deterministic static Appliance Deploy YAML generator (#565)

Status: **Draft / CI-only generation verification**, no change to active
`.github/workflows/appliance-deploy.yml` and no runtime consumption.
The existing P1 JSON remains **metadata**, not authorization. This stage is
distinct from the P3 consumer migration and the P4 synthetic onboarding.

## Reviewed inputs and output

- `gway_remote/data/appliance-targets.v1.json` via
  `catalog_shadow.load_catalog()` supplies the seven ordered, closed-schema
  known repository/adapter/probe records. Its registry parity remains strict;
  invalid/duplicated/missing properties fail closed.
- `gway_remote/appliance_workflow_generator.py` has a **separate, reviewed**
  two-track `TRACKS` allowlist for the six *currently dispatchable*
  repositories. It compares that set and order against
  `deploy_dispatch.TARGETS` and `deploy_failure_issues.REPOSITORIES`.
  **`ocpp-reports` is known but remains unadmitted** until separate #564
  acceptance; `ocpp-simulator` is absent. A catalog-only insertion cannot
  cause a job to be generated.
- Four **reviewed static templates** under `gway_remote/data/`:
  `appliance-deploy.skeleton.yml.in` fixes trigger, inventory admission,
  permissions, actor/node checks, runner, artifact/reporter/publisher,
  GH_TOKEN sources, concurrency and retention. Job templates
  `appliance-deploy.first.yml.in`, `appliance-deploy.linked.yml.in`,
  `appliance-deploy.bastion.yml.in` fix the two-track execution semantics,
  `always()` gated by successful admission and Bastion stage-only.
  Templates are local, committed and not controlled by JSON input.
- In-memory output: `.github/workflows/appliance-deploy.yml`; **the checked-in
  file itself is unchanged in P2**. No matrix expansion, dynamic
  `needs`, workflow generation at GitHub Actions runtime or automatic
  addition of approved hosts.

Run the stdlib-only, operator-side generator locally:

```bash
python3 -m gway_remote.appliance_workflow_generator --check
python3 -m gway_remote.appliance_workflow_generator --render
```

`--check` compares the full UTF-8 byte stream against the committed YAML.
A mismatch returns nonzero and emits a bounded unified diff; it **never**
writes, repairs or dispatches. `--render` only prints to stdout for separate
review/commit by an authorized developer. There is no `--write` option.
The `validation` job in PR-only `.github/workflows/ci.yml` invokes **only
`--check`**. A developer must explicitly commit any reviewed YAML change.
On the P2 baseline the generated output is **9,975 characters / 9,976 bytes
UTF-8, identical byte for byte** to the preexisting static YAML. The existing P0 semantic parser/tests
are additional independently implemented constraints.

## Fixed DAG and security guarantees

Two independent chains depend on `admission`:

1. `ocpp_csms`
2. `gway_lcd_sound` → `gway_agent_ops` → `gway_ap_kiosk` →
   `gway_rfid` → `gway_bastion` (**stage-only**, not activated)

The `report` job depends on `admission` plus all six component jobs.
The fixed gate checks `workflow_dispatch`, `github.actor == 'arthexis'`,
`needs.admission.result == 'success'`, `inputs.node == 'gway-001'`
and the exact selected repository. `always()` on chained/report jobs
does not bypass admission. Admission uses the independent root-owned
Ansible policy and denies other nodes. GitHub permissions remain only
`contents: read` and `issues: write`; no new token, environment or
runner. The trusted dispatch secret is used only in the six deployment jobs;
the issue publisher uses `github.token`. Publisher failures remain visible.
The sanitized report, independent per-job outcomes, `unknown/skipped`
handling, bounded logs, `if-no-files-found: error` and 14-day artifact
retention remain unchanged. Public `target_export` keeps its separate
numeric `schema=1`, the ordered seven targets and the same revision
fingerprint. No Bastian activation/health inference (stage is not active).

## Offline acceptance

- `tests/deployment/test_appliance_workflow_generator_p2.py`: full-byte
  golden parity, deterministic repeated compilation, CLI non-write
  restrictions, failure on missing/duplicate template slots, drift of
  permissions, actor, concurrency, retention, secret and job guards,
  six-vs-seven admission, complete report map and DAG, stage-only, corrupt
  catalogs and unchanged target_export. Existing
  `tests/deployment/test_appliance_contract_p0.py` checks semantic DAG,
  `always()`, forbidden `true ||` guards, duplicate report AST keys,
  artifact publisher visibility and root-owned inventory invariants.
- `tests/infrastructure/test_appliance_interleaving_p2.py`: enumerate
  six ordered schedules for two abstract activities. Explicitly detect
  potential overlaps between the distinct backend and Appliance workflow
  groups, the lack of a common backend/appliance Python lock, the shared
  Appliance/Report group, the appliance flock, the Watchtower lock,
  `appliance_watch --apply` busy check and its limitations. **All tests use
  isolated files/mocks; no real runner, host, GitHub dispatch or install.**

## Known concurrency gap — requires separate operational evidence

- `appliance-deploy.yml` and `appliance-report.yml` use the Actions
  concurrency group `gway-001-appliance`.
- `deploy-backend.yml` uses **another** group:
  `gway-001-appliance-report`. Its ordinary
  `deployment.deploy()` / `deploy.sh` path is not shown acquiring
  `best_effort.appliance_lock`. Some optional stage/Watchtower paths have
  distinct `deploy.lock` files; these are **not** a cross-workflow mutex.
- The Watchtower job follows the backend job in its own workflow and uses
  the Watchtower-specific lock. This sequencing does not serialize it
  with an unrelated Appliance workflow dispatch.
- `appliance_watch._busy()` watches only pending Appliance Deploy runs
  and its SHA reservation limits repeated dispatch; it does not certify
  that Deploy Backend has stopped. Manual `deploy-batch --all` shares
  `appliance.lock` with other appliance executions but not necessarily
  with backend deployment.

The offline model admits overlapping schedules in the absence of a
common group/lock. **This is a risk, not evidence of actual simultaneous
runners or failed production deployment.** P2 does not modify locks or
scheduling. Do not infer real capacity or exclusivity from shared runner
labels; a separate future acceptance must inspect the real runner topology
and interleavings before changing execution policy.

## #564 compatibility, upgrade and rollback

#564 would add Reports after CSMS plus its choice, job, summary/reporter
mapping and inventory admission. P2 deliberately **does not** do that.
Once #564 is independently accepted, a follow-up, reviewed change must
expand `TRACKS` and the linked job template, amend the workflow and
update semantic/byte-golden tests together; CI must run over the resulting
combined HEAD. Do not silently reconcile the draft by parsing its branch.

If P2 validation causes CI issues, revert its generator, template and
CI-check changes to the previous static-workflow-only model. The live
`appliance-deploy.yml` and root/node-owned inventory and MCP manifests
are not modified by P2, so metadata rollback needs no runtime migration.
This **does not** roll back an already deployed backend. Any later merge
will trigger the existing `push` deploy-backend workflow and needs a
separately authorized and supervised acceptance.

No P3 migrations, AgentOps submit, workflows, Ansible, nodes or deployments
are part of this draft increment. Keep issue #565 open for P2–P4 gates.
