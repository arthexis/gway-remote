# MCP M2: supervised field connectivity preflight

Status: M1 #234 and clean M2 #238 are merged. The read-only MCP transport exists,
but a ChatGPT connection and production exposure have **not** been verified.

## Scope and ownership

ChatGPT -> authenticated HTTPS MCP ingress -> Gway Remote MCP on Gway-001
(loopback 127.0.0.1:8770) -> fixed Agent Ops adapter -> Agent Ops.

This is a read-only connectivity increment. No `agent_submit`, GitHub issue
mutation, Codex invocation, Android dependency, or second queue/worker.

## Gway-001 field-agent checklist (read-only until rollout approval)

1. Record deployed SHAs and service states for `gway-remote` and
   `gway-agent-ops`. Compare the deployed Remote version against merged M2.
   Do not activate a service simply to test a read-only check.
2. From Gway-001 only, validate the intended SSH host supplied in issue #233
   against existing inventory and pinned known_hosts. Do not disable strict
   host-key checking or silently accept a new host key. Stop on mismatch.
3. Over the verified SSH connection, inspect ingress host, DNS, TLS termination,
   applicable Nginx vhost/includes, restricted private route to Gway-001 and
   upstream ownership. Read configuration without printing credentials.
4. Verify which authenticated HTTPS endpoint can actually reach the MCP
   process. Remember that `127.0.0.1` belongs to each host separately; a
   remote gateway cannot proxy to Gway-001 through its *own* loopback.
5. Establish the exact ChatGPT remote MCP connection and authentication
   requirements. Current `GWAY_MCP_BEARER_TOKEN` is a private transport
   prerequisite, **not** proof that ChatGPT can authenticate to this server.
   Use an operator-authorized credential flow without putting tokens in chat,
   URLs, issues, shell history, logs or repository files.
6. Before activation, submit an ingress plan specifying hostname, TLS certificate
   validity, trusted upstream route, authentication boundary, allowed HTTP path,
   rate limiting, and how unrelated vhosts remain unchanged. Require separate
   rollout authorization before writes or reloads.
7. Once authorized, enable the service and gateway narrowly. Verify rejection
   of missing/wrong authentication, browser Origin, unknown method and unknown
   tool. Then check initialize, tools/list and all four read-only tools using
   the authenticated connector. Never call submit in M2.
8. Report PASS / FAIL / BLOCKED and sanitized evidence: deployed SHAs, endpoint
   HTTP statuses, MCP protocol version, discovered tool names, ingress host
   identity verification outcome and any remaining connector issue.

## Security boundaries

- Keep MCP listener bound to `127.0.0.1:8770` on Gway-001.
- Do not expose mobile API port 8765, SSH, WireGuard or Codex publicly.
- Agent Ops owns admission, one execution slot, approvals, history and policy.
- PR CI is authoritative. Do not require post-merge main CI.
- If a gateway requires a tunnel, verify endpoint identity on both ends and
  make tunnel changes only in a separately reviewed and authorized rollout.
- A successfully initialized MCP transport is not evidence that ChatGPT is
  connected or that Agent Ops execution is permitted.

## M3 entry criteria

M3 may add only a separately reviewed, explicitly approved `agent_submit`
path after the live read-only connection has passed. It must preserve frozen
UTC invocation identity, exact target label and trust revalidation, audit logs,
server-derived MCP provenance, the single-slot queue and observe-on-timeout.
