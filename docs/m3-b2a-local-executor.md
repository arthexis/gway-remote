# M3 B2a: local node-side executor (not publicly enabled)

Parent [#317](https://github.com/arthexis/gway-remote/issues/317), successor to merged B1 [#330](https://github.com/arthexis/gway-remote/pull/330).

## Implemented

`gway_remote.node_exec_worker.Jobs` is a **local-only** submission/status/cancellation API. It stores a job journal in a private SQLite database and starts one independently managed *user* systemd transient service per job. The transient service calls the fixed Python module; the command itself is **never interpolated into a systemd command line**. Its worker launches `/bin/sh -c` under the service's Linux UID, captures bounded combined output and commits the job's exit status and timestamps.

Each job has `MemoryMax=128M`, `TasksMax=32`, `RuntimeMaxSec=70s` (60s worker timeout plus cleanup headroom), `KillMode=control-group` and an explicit job name. Cancellation is an independent `systemctl --user kill --kill-whom=all` call; no HTTP disconnect triggers cancellation. Failed or unobservable jobs are never silently replayed: `reconcile()` reports `unknown` if the systemd unit disappears without a committed result. There is one active job per node initially; output is capped to 1 MiB with a 16 KiB result-page limit.

## Ansible installation (opt-in, no remote execution)

The existing `ansible/roles/gway_remote` role includes
`tasks/node-exec-prepare.yml` **only** when `exec_prepare=true`.
This avoids provisioning an executor account on Watchtower or other hosts
during normal deployments.

After reviewing the target is the intended `gway-001` Pi, run its ordinary
operator deployment with explicit extra-vars:

```sh
./deploy.sh -e exec_prepare=true
```

This creates the **locked, non-login** `gway-exec` account, its dedicated
primary group and private `/var/lib/gway-exec` directory (0700).
Supplementary groups are removed and verified. Account name and state path
cannot be overridden to a privileged identity. Ansible does **not** create
SSH keys, a command listener, sudo rights or an MCP execution endpoint.

For an approved field test that needs a persistent user systemd manager,
the separately opt-in variant is:

```sh
./deploy.sh -e exec_prepare=true -e exec_enable=true
```

The second variable invokes `loginctl enable-linger gway-exec` once when
needed. It does not enable command execution through MCP. **Do not enable
linger on Watchtower or an unapproved target.** A future removal/revocation
procedure should explicitly disable linger and safely retain or retire job
records; regular repeat deployments do not remove an existing account.

The worker's systemd-run invocation sets a fixed import path to the
root-owned `/opt/gway-remote` package and working directory to the private
job directory. It must never rely on a writable Python module path.
This is preparation only; test on the actual Pi that the user manager is
reachable and the cgroups behave as expected before any remote executor is
activated.

**Field gates still mandatory:** verify the `gway-exec` identity has no
sudo/polkit, privileged groups, Docker socket, OCPP state write permissions,
or access to SSH/WireGuard secrets. Test job subprocess lifetime, descendant
cancellation, disk cap, memory/task limits and restart recovery. Real
`node_capabilities.execute_available` remains **false**. Nothing in this
PR installs or enables a network listener or lets Watchtower run commands.

## B2b remains a separate gated PR

Implement and field-test an authenticated node-side transport and Watchtower relay. Bind an execution approval to **exact** command bytes, node, current attested host identity, expiry, issuer, scope `gway:execute`, and unique request ID. Server must enforce one-shot/idempotent execution and independently authorize result/cancel, never trust `approved=true` or client-selected hostname/address. Add durable per-request deduplication, bounded journal retention and total disk quota, safe activation/rollback, and authorized real ChatGPT MCP acceptance. B2a does not grant these capabilities.

**Deployment commands remain a separate future MCP tool**, not a new privilege for the generic shell account. No Watchtower shell, no production charging service changes, no Docker/container runtime.
