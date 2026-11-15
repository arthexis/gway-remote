# MaintenanceFence V1-D0 — bounded source inventory and lock-order contract (#561)

**Offline declaration only.** This commit does not wire a lock, alter a runtime,
start AgentOps, deploy, change GitHub workflows, or change SQLite. V1-A/B/C1/C2
remain unchanged. D0 does **not** prove global exhaustiveness: tests guarantee
that the *declared* critical paths still contain the audited source anchors.
Unlisted or external executors remain gaps, not implicit permissions.

## Source-backed effects inventory (gway-001 only)

| ID | Audited source | Side-effect frontier | Existing independent guard |
| --- | --- | --- | --- |
| appliance_workflow | `.github/workflows/appliance-deploy.yml` | GitHub dispatch → Ansible jobs | GitHub queue `gway-001-appliance` |
| backend_push | `.github/workflows/deploy-backend.yml` | main push → deploy.sh / Watchtower Ansible | GitHub queue `gway-001-appliance-report` |
| simulator_schedule | `.github/workflows/ocpp-simulator-deploy.yml` | schedule → installer script → Simulator deploy.sh | GitHub queue `ocpp-simulator-gway-001-auto-install`; external installer flock not attested |
| github_dispatch | `gway_remote/deploy_dispatch.py` | POST workflow_dispatch | downstream workflow only |
| provider_broker | `gway_remote/mcp_deployment_broker.py` | declaration runner `subprocess.run` | `flock(.managed-provider.lock)` |
| provider_worker | `gway_remote/mcp_deployment_broker.py` | worker invokes provider broker | per-request flock + provider flock |
| node_exec_worker | `gway_remote/node_exec_worker.py` | `subprocess.Popen` of allowed command | durable request ledger, not a shared fleet fence |
| watchtower_manual_ledger | `gway_remote/manual_deploy_broker.py` | manual deployment reservation (not execution) | separate SQLite ledger |
| agentops_federated | **EXTERNAL** `arthexis/gway-agent-ops` | AgentOps submit/executor | unverified here; no local source attestation |

**Boundaries:** the resource planner names `gway-001` and `ocpp-abb-N`,
not `Watchtower` nor `customer.gelectriic.com`; the backend push and
appliance workflow can affect remote systems beyond the modeled root.
Catalog `node/gway-001` is intentionally conservative for broad entrypoints;
narrow Simulator/provider siblings have *potential* independence only if all
actual service, network, filesystem and database effects are independently
declared. Tests do not claim those footprints are complete. Existing
`flock` file paths and GitHub concurrency groups are **not** equivalent
to each other. A workflow queued by GitHub does not own an OS lock.

## Proposed global lock-order discipline (not executable)

1. GitHub queue precedes any local work when initiated from GitHub. No
   ability to acquire/release that queue from node-local code is assumed.
2. Acquire a **single durable node coordinator** for the complete canonical
   resource set (V1-D1 future), with authenticated principal and boot.
3. Hold SQLite `BEGIN IMMEDIATE` **only** for journal/state transitions,
   commit and release transaction before acquiring legacy OS flock.
4. Acquire legacy `flock` in one globally documented order, then re-check
   exact principal, SHA, request, lease, generation and held ownership.
5. Verify an execution fence immediately before each actual side effect;
   the process and children must not outlive the coordinator's ownership.

No waiting for GitHub, network calls or subprocess while holding the SQLite
write transaction. The coordinator must prevent a stale actor from resuming
after a higher generation; if target operations do not consume a fencing
generation, simply taking a lock beforehand is insufficient. A crash, missing
release receipt, lease expiry, changed boot, external uninstrumented work or
4096-event journal exhaustion means **uncertain / no new admission** until
quiescence has been independently verified. Avoid automatic recovery.

## Future rollout — separate authorizations

- **D1**: prove effective local owner/boot/clock trust, fd-safe journal
  lifetime, durable bounded capacity strategy and conflict serialization.
- **D2**: observer/shadow-only routing comparison on a canary, including
  real external source inventory and missing paths.
- **D3**: enforce *before effects*, through explicit canary authorization and
  staged rollback. Only then expand workflows/broker/AgentOps/other nodes.

The catalog intentionally cannot certify agent-side runtime, deploy.sh in
`ocpp-simulator`, Watchtower services, external runner actions, real locks,
process quiescence or all repo entrypoints. Those are explicit blockers to
operational acceptance, **not** blockers to reviewing this pure D0 inventory.

## Hermetic acceptance

Run `python -m unittest tests.core.test_maintenance_fence_effect_inventory_v1d0 -v`.
It checks the exact route set, source anchors against the checked-out repo,
rejects missing/duplicate/changed routes, tests conservative and potential
conflicts, tests acyclic lock order and preserves the external AgentOps gap.
An anchor is only evidence that a reviewed code pattern remains present, not
a proof that there are no alternate effect paths.

Retain #561 open, `R6 unchecked`, `BeforeAvailable=Quarantined`.
