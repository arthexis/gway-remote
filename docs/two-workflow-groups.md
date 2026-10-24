# Two parallel appliance deployment tracks

The manual `.github/workflows/appliance-deploy.yml` runs two independent
job chains when `repository=all`:

- **SVP / OCPP:** `ocpp-csms` → `ocpp-reports` → `ocpp-simulator`.
- **Gateway:** `gway-lcd-sound` → `gway-agent-ops` →
  `gway-ap-kiosk` → `gway-rfid` → `gway-bastion` (stage-only).

There is **no cross-track `needs` dependency**. Both chains may execute
concurrently on the self-hosted GWay-001 runner if capacity permits; within
each chain, `needs` serializes deployments and `always()` allows
fail-forward after an unsuccessful predecessor. Each job calls the
target-specific `deploy-batch` entrypoint, which delegates to the
repository's deployment contract and verified-revision skip logic.

The single workflow-level `gway-001-appliance` concurrency group prevents
two *workflow runs* from overlapping, **not jobs within one run**.
Do not add a job-level global mutex that defeats the two-track design.

Shared resources (APT/dpkg, systemd manager, nginx) still require safe
per-resource synchronization inside installers. The two tracks do not
guarantee absence of resource contention; any observed contention must be
fixed at the resource boundary, not by reintroducing cross-track dependencies.

A single report job waits for both tracks and summarizes individual
outcomes, including skipped and failed jobs. No post-merge deployment or
automatic field validation is introduced by this change.
