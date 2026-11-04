# M3 B2a: local node-side executor (not publicly enabled)

Parent [#317](https://github.com/arthexis/gway-remote/issues/317), successor to merged B1 [#330](https://github.com/arthexis/gway-remote/pull/330).

## Implemented

`gway_remote.node_exec_worker.Jobs` is a **local-only** submission/status/cancellation API. It stores a job journal in a private SQLite database and starts one independently managed *user* systemd transient service per job. The transient service calls the fixed Python module; the command itself is **never interpolated into a systemd command line**. Its worker launches `/bin/sh -c` under the service's Linux UID, captures bounded combined output and commits the job's exit status and timestamps.

Each job has `MemoryMax=128M`, `TasksMax=32`, `RuntimeMaxSec=70s` (60s worker timeout plus cleanup headroom), `KillMode=control-group` and an explicit job name. Cancellation is an independent `systemctl --user kill --kill-whom=all` call; no HTTP disconnect triggers cancellation. Failed or unobservable jobs are never silently replayed: `reconcile()` reports `unknown` if the systemd unit disappears without a committed result. B2b-1 adds a root-controlled per-appliance concurrency policy: by default up to `max(1, min(os.cpu_count() - 1, 8))` active jobs, with a bounded explicit override `max_active` from 1 through 8. On single-core nodes, one job is still permitted. This leaves one logical CPU outside the job-slot count when possible, **not** a hard CPU reservation. Each job retains its individual cgroup limits, so operators should consider aggregate memory pressure when raising concurrency. The private SQLite journal enforces the appliance-wide admission count atomically, regardless of caller-supplied node labels. Output remains capped to 1 MiB with a 16 KiB result-page limit.

## Standard node bootstrap and Ansible convergence

**No per-node execution flags.** Every authorized, newly bootstrapped node
receives the same **dormant** executor prerequisites. The standalone
`wireguard_satellite.py` client prepares the fixed `gway-exec` system user,
group, locked account, private `/var/lib/gway-exec` directory (0700), and
persistent systemd user-manager linger **after successfully establishing
WireGuard**. It uses standard Debian system tools; bootstrap never requires
Ansible. Existing successful bootstrap reruns converge the same prerequisites.
Host-identity repair alone does not mutate executor installation.

Subsequent Ansible deployments use the existing `gway_remote` role's
`node-exec-prepare.yml` automatically **only on hosts whose Ansible-reported
hostname matches `gway-NNN`**. This maintains the account/group, private
directory and linger without options. A Watchtower install is not a node
install, so the node preparation task must not be applied there. No special
`exec_prepare` or `exec_enable` flags remain. Both paths are intended to
converge equivalent local prerequisites.

**This is not execution authorization.** There is no MCP executor listener,
SSH command key, new sudo/polkit grant, or remote dispatch endpoint in B2a.
The existing Watchtower enrollment ledger is the sole source of node identity;
B2b must add an explicit default-deny *central execution eligibility* setting
there, together with attestation/readiness checks and request-specific operator
approval. Installed prerequisites, active user linger, or a WireGuard handshake
alone must never imply `execute_available=true`.

The transient worker loads modules from root-owned `/opt/gway-remote` when
Ansible has deployed the package. On freshly bootstrapped satellites that have
not yet received the package, the account exists but cannot run jobs. Central
execution eligibility must remain disabled until that package and the
authenticated transport are installed and field-verified.

Before B2b is enabled: verify no sensitive filesystem access, privileged
groups or service-control rights; validate user systemd manager, cgroup
limits, descendant cancellation, output limits, restart recovery, and the
failure behavior with no active charging. Revocation should prevent new
submissions centrally without implicitly killing already-running jobs.

## B2b remains a separate gated PR

Implement and field-test an authenticated node-side transport and Watchtower relay. Bind an execution approval to **exact** command bytes, node, current attested host identity, expiry, issuer, scope `gway:execute`, and unique request ID. Server must enforce one-shot/idempotent execution and independently authorize result/cancel, never trust `approved=true` or client-selected hostname/address. Add durable per-request deduplication, bounded journal retention and total disk quota, safe activation/rollback, and authorized real ChatGPT MCP acceptance. B2a does not grant these capabilities.

**Deployment commands remain a separate future MCP tool**, not a new privilege for the generic shell account. No Watchtower shell, no production charging service changes, no Docker/container runtime.

## B2b-1: durable request IDs (local implementation)

Local `Jobs.submit(node, command, request_id=<32 lowercase hex>)` accepts a caller-supplied stable ID. An atomic SQLite transaction checks for an existing ID **before** capacity enforcement, returns the same ID for an identical node/command and rejects reuse with different command bytes or node identity. No duplicate launch occurs for a successful, in-progress, failed or terminal request. The client must generate a fresh cryptographically random ID for each new operation and reuse it on retries; a new ID always represents a new operation. Historical records are retained with the existing 7-day/256-job bounds; expired IDs cannot be deduplicated, so B2b must define a corresponding maximum remote retry/replay window.

On each node Ansible maintains `/etc/gway-remote/executor.json`, owned by root, mode 0644, with `{"max_active":"auto"}` by default or a bounded integer `1..8`. Override through the inventory variable `gway_remote_exec_max_active`. The worker rejects unsafe/writable configuration files and invalid values. Default `auto` is `max(1, min(os.cpu_count() - 1, 8))`. No command inference or mutation-aware lock is attempted; higher-level B2b workflows must coordinate conflicting configuration writes.

This adds **no remote execution transport, approval, or MCP tool**. Watchtower must implement its separate durable request ledger and authenticated identity binding before dispatch to this local API. The per-appliance limit is a guardrail, not a promise of CPU isolation or mutual exclusion for shared configuration writes.
