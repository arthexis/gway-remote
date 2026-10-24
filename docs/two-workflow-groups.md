# Two workflow groups for GWay-001

This proposal preserves **two operational groups**, not one workflow per repository.

## Group A — Deployment

Keep `.github/workflows/appliance-deploy.yml` as the single manual
deployment orchestrator. Its per-repository jobs are **jobs**, not separate
workflows. They remain serialized, report individual outcomes, and use the
same `gway-001-appliance` concurrency group.

Each repository's `deploy.sh` owns its verified same-commit fast path.
No `--force` is needed for a healthy, already installed revision.
Deployment does **not** implicitly execute physical-device tests.

## Group B — Field validation

Use `.github/workflows/appliance-field-tests.yml` for explicit,
manual, non-deployment validation on GWay-001. Initially it exposes the
existing `system-health` registered task. Hardware-specific LCD,
RFID, AP, and charger checks must be added only after their non-destructive
test entrypoints and prerequisites are audited.

Field validation must not call `deploy-batch`, install packages, restart
services, or mutate charger state. It uses the same appliance concurrency
lock as deployment, so the two groups do not contend for hardware.

## Out of scope

- No eight per-repository deployment workflows.
- No post-merge main CI for the appliance.
- No automatic field tests after deploy.
- No migration of Android APK build/release workflows in this PR.
- Legacy `remote.yml` dispatch routes and backend auto-deploy are a
  separate migration: do not disable them without tracing their callers.

## Acceptance

1. Both operational workflows are manually dispatched.
2. Deploy remains selectable by repository and retains per-job results.
3. Field checks are read-only and never call deployment.
4. Both share the appliance lock.
5. CI validates the YAML contracts without assuming a specific job graph.
