# M3 B1 — generic shell job contract (preview only)

Parent: [M3 #317](https://github.com/arthexis/gway-remote/issues/317).
Increment: [B1 #329](https://github.com/arthexis/gway-remote/issues/329).

## Scope and hard boundary

B1 exposes `node_exec_preview(node, command)` through the existing
Watchtower-local MCP gateway. It is a **read-only preview**. It displays the
exact command string and the canonical registered node after checking the
fresh enrollment inventory reports an active **attested** identity. It
returns a random `preview_id`, a command SHA-256 fingerprint, preview expiry
and *proposed* execution limits. Neither the digest nor the preview ID is
authorization, a durable queued job, or permission to run anything.

**Execution is not implemented or authorized in B1.** MCP gateway tools
`node_exec`, `node_cancel`, and `node_result` remain unadvertised
and disallowed, including forged calls. The verifier still accepts only
`gway:read`. Every enrolled node must retain `execute_available=false`.
Neither the Watchtower nor a Pi runs the command. Deployments are deferred
to a separate future MCP tool using existing approved GitHub/Ansible workflows.

## Future B2 contract (not activated)

- Execute the exact shell string under a **separate non-root Linux user**
  `gway-exec` on the target Pi. Do not parse shell syntax or maintain
  command/argument catalogs. No sudo, admin group, credential access,
  access to private SSH/WG keys or uncontrolled OCPP service writes.
- Define one idempotent job ID per accepted submission. Versioned statuses:
  `queued`, `running`, `succeeded`, `failed`, `cancelled`,
  `timed_out`, `unknown` (when recovery evidence is lost).
- Return immediate completion within an **up to 10-second** synchronous
  window; otherwise return the job ID and `running`. HTTP/MCP disconnects
  **do not stop jobs**. `node_result` retrieves durable bounded output
  with a cursor and final exit code after reconnect or service restart.
- `node_cancel` is a distinct authorized, audited operation, bound to the
  exact job and node. Terminate the entire systemd cgroup when explicitly
  cancelled. Never silently retry a submission after a network timeout.
- A dedicated `gway:execute` permission with an expiring, single-use
  approval bound to command bytes/digest, requested node, pinned identity,
  request ID, limits and subject is required before execution. A client
  boolean `approved=true` is never sufficient.
- Linux OS-user permissions are the primary access boundary. The B2 agent
  must first audit `gway-exec` groups, filesystem ACLs, sudo/polkit,
  sockets, SSH/WG secrets and OCPP state access. A non-root user is not
  inherently read-only.
- Use lightweight systemd transient units/scopes/cgroups on the node to
  contain and terminate the *whole descendant tree*, without Docker or
  additional container runtimes. Validate actual installed Pi systemd
  version/cgroup delegation before enabling. Candidate limits: memory
  128MiB, tasks 32, one concurrent command per node, 60-second standard
  lifetime, 1MiB bounded output spool; measure before enforcement.
  Longer tasks need a separately authorized policy class, not a 10-second
  kill. Retention and spool quotas must be bounded.
- Watchtower is a policy/dispatch/audit relay **only**. It must not
  receive execution privileges, run any submitted shell, or forward
  host/network override parameters. Keep the current Bastion, WireGuard,
  seven read-only MCP tools, and all charging services unaffected.

## B1 acceptance

Tests verify that preview is side-effect-free; shell strings containing pipes
and metacharacters are preserved exactly; unknown, unregistered,
unattested or stale node snapshots fail closed; output/result schema and
state transitions reject malformed records; and execution/cancel/result
MCP calls are rejected at the gateway.

A successful B1 preview must show `status=preview_only` and
`execute_available=false`. This is **not** proof that B2 dispatch, durable
storage, approvals or systemd integration work yet.
