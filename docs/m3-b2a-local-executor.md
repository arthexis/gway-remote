# M3 B2a: local node-side executor (not publicly enabled)

Parent [#317](https://github.com/arthexis/gway-remote/issues/317), successor to merged B1 [#330](https://github.com/arthexis/gway-remote/pull/330).

## Implemented

`gway_remote.node_exec_worker.Jobs` is a **local-only** submission/status/cancellation API. It stores a job journal in a private SQLite database and starts one independently managed *user* systemd transient service per job. The transient service calls the fixed Python module; the command itself is **never interpolated into a systemd command line**. Its worker launches `/bin/sh -c` under the service's Linux UID, captures bounded combined output and commits the job's exit status and timestamps.

Each job has `MemoryMax=128M`, `TasksMax=32`, `RuntimeMaxSec=70s` (60s worker timeout plus cleanup headroom), `KillMode=control-group` and an explicit job name. Cancellation is an independent `systemctl --user kill --kill-whom=all` call; no HTTP disconnect triggers cancellation. Failed or unobservable jobs are never silently replayed: `reconcile()` reports `unknown` if the systemd unit disappears without a committed result. There is one active job per node initially; output is capped to 1 MiB with a 16 KiB result-page limit.

## Local host preparation and gate

**Do not deploy or activate on production automatically.** This source change does **not** provision the account, service manager, SSH keys, public routes, or MCP tools; `node_capabilities.execute_available` remains **false**. Field readiness requires a deliberately reviewed Ansible role or console procedure that provisions a dedicated unprivileged `gway-exec` account with a private `/var/lib/gway-exec` directory (owner `gway-exec`, mode `0700`) and a working, persistent user systemd manager (systemd on actual Raspberry Pi). Start the job broker and transient units as that account, never through a shell-enabled privileged service. No sudo, polkit authorization, privileged groups, Docker socket, OCPP configuration write access, or access to private SSH/WireGuard keys. Audit effective ACLs and permissions rather than assuming non-root implies read-only.

The worker is a Python API/testable module only in B2a. On an actual Pi, deployment must first prove that `systemd-run --user` works with this service account, that unit cgroups enforce limits, that the installed Python package resolves from a transient user's systemd context, that a unit survives the submitting process exit, and that cancellation kills forked/background descendants. Test reboot/restart journal recovery and inability to read protected system material before enabling any remote dispatch.

## B2b remains a separate gated PR

Implement and field-test an authenticated node-side transport and Watchtower relay. Bind an execution approval to **exact** command bytes, node, current attested host identity, expiry, issuer, scope `gway:execute`, and unique request ID. Server must enforce one-shot/idempotent execution and independently authorize result/cancel, never trust `approved=true` or client-selected hostname/address. Add durable per-request deduplication, bounded journal retention and total disk quota, safe activation/rollback, and authorized real ChatGPT MCP acceptance. B2a does not grant these capabilities.

**Deployment commands remain a separate future MCP tool**, not a new privilege for the generic shell account. No Watchtower shell, no production charging service changes, no Docker/container runtime.
