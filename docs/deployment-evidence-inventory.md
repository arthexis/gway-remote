# Managed deployment evidence inventory (M3, issue #225)

Source inspection on 2026-10-28. **Not** a live host audit. The authoritative current catalog is `gway_remote.reconcile.TARGETS`; `probe_registry.PROBES` provides component-specific health/revision probes. `deployments.inventory` iterates `TARGETS` and applies the node inventory allowlist. CLI shorthand/--all selects from the approved catalog, not arbitrary repositories. Re-run this inventory when TARGETS changes.

| Target | Installed revision evidence consumed by Remote | Runtime probe type | Observed gap vs contract v1 |
| --- | --- | --- | --- |
| ocpp-csms | `~/.local/share/ocpp-csms/current` symlink, 12-hex (optional -dev) | `csms` | No separate staged/activated evidence or probe timestamp in status envelope |
| ocpp-reports | `/usr/local/bin/ocpp-reports` executable link resolving under `releases/<40-hex>` | `executable` | Verify real role-specific runtime independently; no staging evidence in Remote |
| ocpp-simulator | `~/.local/share/ocpp-simulator/current` link, 12-hex | `executable` | Confirm whether CLI-only runtime should be `not_applicable`, not merely executable presence |
| gway-lcd-sound | `~/.local/share/gway-lcd-sound/current` link, 12-hex optional -dev | `lcd` | User-service runtime evidence and staged state not in shared envelope |
| gway-agent-ops | `~/.local/bin/agent` executable link resolving under `releases/<40-hex>` | `executable` | No root deploy.sh in original audit; inspect actual role/installer before changing; service health not implied by binary |
| gway-ap-kiosk | `/var/lib/gway-ap-kiosk/installed-revision` plain file, 40-hex | `systemd:gway-kiosk-status.service` | Revision file is not activation/runtime proof by itself |
| gway-rfid | `~/.local/share/gway-rfid/current` link, 40-hex | `systemd:gway-rfid.service` | User-systemd semantics must be checked; staging and freshness not explicit |
| gway-bastion | `/opt/gway-bastion/deployment/{staged,activated}.json`, each verified against `releases/<sha>/REVISION` | Special evidence reader: activated => unknown, staged-only => not_applicable | M1 already implemented in PR #226 and fixed in #240; no independent activated runtime health probe |
| gway-remote (orchestrator itself) | Root `deploy.sh` writes `~/.local/state/gway-remote/deployed-commit` after normal Ansible; checks installed CLI, status schema and timer for skip | Self CLI/status and timer | Not a `TARGETS` entry; marker is only a hint, not independent revision proof; self-status needs separate contract treatment |

## Current consumer behavior and limitations

- `status.status` distinguishes attempted SHA and journal status from `installed_revision`, but uses `installation` for **attempt** state (`never-attempted`, `failed`, `installed`, `interrupted`, `unknown`). Do not reinterpret it as the new contract's `installation_state`.
- `deployments.inventory` separately reports `installed_sha`, `latest_sha`, `attempt_status`, `revision_status`, and Bastion `release_state`/`staged_sha`. A local verified link is not necessarily a runtime-health check; remote nodes intentionally do not receive local probe evidence.
- `status.status(depth="quick")` forces health `unknown` except Bastion evidence; deep mode uses `component_health`. Both currently omit per-component probe timestamps and errors from independent runtime checks.
- `probe_for` returns an unknown probe for any catalog target not listed in `PROBES`; this is fail-closed. Bastion is handled separately. The status iteration is over TARGETS, not over PROBES.
- Revision evidence conventions differ: short SHA symlinks, full SHA symlinks, installed-revision file, and Bastion dual JSON. Preserve those distinctions via adapters rather than rewriting installers.
- `installed_revision` checks file/symlink shape, but further trust-boundary hardening (e.g. allowed release roots, ownership, symlink targets) requires repository-specific inspection before making stronger claims.

## M4 recommended order

1. Add pure fixture-driven mapping tests in Remote for each catalog target, explicitly distinguishing attempted, installed/activated, staged, runtime and stale/unknown; assert TARGETS coverage, including unknown probe fallback.
2. Adapt Remote status/API to expose a **new** versioned evidence object without changing legacy `installation` or `health` field meanings. Bastion adapter first; preserve staged-only semantics.
3. Validate the actual installer/Ansible role and runtime status entrypoint per repository before proposing repo-local probe changes. Group compatible probes into small PRs; keep schema-pinned CSMS, role-specific Reports and protected Bastion semantics.
4. Test remote-node status as `unknown` when no remote evidence exists; never treat a local operator's installation as evidence for a satellite.

No production SSH, service restart, database mutation, hardware action, or deployment was performed for this inventory.
