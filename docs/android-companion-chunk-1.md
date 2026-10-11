# Android companion: Phase 1, chunk 1 — verified inventory

This document records the backend boundaries before adding an HTTPS API. No listener, daemon, deployment, or new runtime dependency is introduced in this chunk.

## Verified source map

- `gway_remote/__main__.py`: argparse entry point, command dispatch, approved workload validation and execution. The `run` and `deploy-batch` paths can modify the appliance; **never expose them by default**.
- `gway_remote/csms_health.py`: `csms_probe()` returns a JSON-serializable dictionary; uses a bounded subprocess runner and does not initiate OCPP sessions.
- `gway_remote/status.py`: `status()` returns `gway-remote/status/v1` data; `format_status()` is terminal-only presentation.
- `gway_remote/github_state.py`: GitHub REST client for reconciliation, **not** an Android identity provider.
- `scripts/install-cli.sh`: standalone Python zipapp installer; does not install or start an HTTP listener.
- `.github/workflows/ci.yml`: Python 3.11 unittest discovery and CLI/Ansible checks.

## Actual execution path

`python -m gway_remote probe-csms` → argparse `main()` → `csms_probe()` → read-only service/storage checks → dictionary → JSON printed to terminal.

`python -m gway_remote status --json` → argparse `main()` → `status()` → dictionary → JSON printed to terminal.

The above functions can be called directly by a future HTTP adapter. No generic shell executor or broad dispatcher refactor is required for these first two operations.

## Decisions for chunk 2

1. Start with an explicit allowlist: `probe-csms` and `status`. No `run`, `deploy-batch`, `logs`, `report-bundle`, or `reconcile` until separately reviewed.
2. Keep execution and presentation separate; HTTP should call the existing Python functions, not capture CLI stdout.
3. Do not add a new persistent process, service, queue, database, or reverse proxy as part of the adapter without a documented hosting decision.
4. Preserve CLI behavior, JSON schemas, and existing command safety policies.
5. Authentication, TLS termination, host binding, node routing and credential rotation require a concrete runtime/deployment decision before exposing any network listener.
6. Initially target the local appliance. The current CLI is local, not a general multi-node network client.
7. Test authorization failures, unknown operations, response serialization, subprocess timeouts, and CLI/API parity before shipping the adapter.

## Remaining operational questions

- Is there an existing HTTPS-capable process on Gway-001 that can host the adapter?
- How should the phone securely reach that endpoint?
- Which existing identity or token lifecycle can be reused?

These are deployment decisions, not reasons to introduce a new service during inventory.
