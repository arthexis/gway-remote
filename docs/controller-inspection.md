# Issue #264 — controller inspection integration

The `deployments --node gway-004 --inspect` command is an **authenticated SSH connectivity probe**, not yet an installed-service inspection. It never enrolls a node or changes the target.

## Watchtower registry source

On Watchtower, the existing root-only administration command now supports `watchtower snapshot` with the same required `--ledger`, `--network`, and `--gateway` settings as `watchtower status`. It emits a schema-2 JSON snapshot containing only node ID, assigned tunnel /32, enrollment state and creation timestamp. The command is **not** exposed through the public enrollment HTTP service.

Provision `/etc/gway-remote/watchtower-inspection.json` on gway-001 through an **already authorized, host-key-verified SSH management channel**. The local file must be owned by the inspecting user and not writable by group/others. Snapshots older than five minutes are rejected. No unattended transfer is enabled until the Watchtower SSH command, authorization and Bastion identity are reviewed.

## SSH trust prerequisites

The controller needs `/etc/gway-remote/inspection-ssh.conf`, owned by the inspecting user and not group/other writable. The effective SSH alias must resolve to the exact private IP in the current Watchtower registry, with `BatchMode yes`, `StrictHostKeyChecking yes` and a pinned, independently verified host key. Existing Bastion/ProxyJump trust remains authoritative. Never use `ssh-keyscan` output as independent identity proof or turn off host-key checks.

The inventory authorizes inspection only for gway-004. Production nodes and customer remain blocked; no deployment permission is granted.

## Acceptance still pending

- Review an authenticated, unattended Watchtower snapshot delivery mechanism with Bastion, avoiding a new public API.
- Validate actual SSH host identity and reachability from gway-001 through the existing Watchtower jump.
- Add read-only remote installed-version/service probes after authenticated SSH passes.
- Obtain PR CI results and gway-004 field receipt. Until then, the PR must remain draft.

## Restricted Watchtower SSH integration

The controller uses the dedicated `watchtower-inspection` SSH alias, resolving to `gelectriic.com`. The alias must have `BatchMode yes`, `StrictHostKeyChecking yes`, an independently verified known-hosts entry, and a dedicated inspection identity. The Watchtower administrator must restrict this identity to `python3 -m gway_remote.watchtower_inspection_command` with no interactive shell or forwarding, and provision read-only access to the existing root-owned enrollment ledger. This is a deployment prerequisite, not an automatically installed privilege escalation.

The client intentionally fails if the trusted SSH configuration is absent. No public enrollment endpoint is used. No production host is automatically adopted.

## Remaining acceptance

The controller now requests a fresh snapshot on each inspection. Before release, validate the actual restricted account, inspect service state on gway-004, verify CI, and add release revision evidence where the installed layout is independently known. Never interpret an absent service or missing revision as proof of non-installation.
