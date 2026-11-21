# MCP internal trust simplification — Stage C (#595)

## Active contract

Watchtower authenticates the public bearer and enforces `gway:read` and
`gway:execute` before any federated RPC. The authenticated node catalog
determines the route; the owning node validates the current tool declaration,
arguments, resources, state and concurrency before dispatch.

The SSH provider wire has two **exact** operations:
- `provider_read` for read-only tools, when the authenticated provider catalog
  explicitly advertises `supports_provider_read=true`. Missing or false
  capability fails closed without contacting the receiver.
- `provider_call` for execute-capable calls, without a serialized OAuth scope.

Both use only `operation`, `node`, `request_id`, `provider`, `tool`,
and `arguments`. The old `authorized_scope` SSH field is rejected at the
sender and receiver, before SSH I/O or provider discovery. Public read cannot
invoke a tool whose live declaration requires execute, even if its classification
changed after the gateway's discovery snapshot.

No change to public OAuth, installed SSH trust, node accounts, AgentOps,
provider registration, Ansible authorization or the **separate private HTTP**
`X-Gway-Caller-Scope` contract.

## History and compatibility decision

Stage B (#586/#589) introduced unscoped execute, a single authenticated
routing snapshot, and the receiver-side operation-bound `provider_read`.
A temporary scoped-read fallback existed for older Stage A receivers.

On 20 November 2026, the owner expressly removed the requirement to preserve
Stage A wire compatibility or enforce a rollback-revision floor. Stage C
intentionally deletes the legacy SSH format. Restoring a pre-B receiver or
gateway is not a supported recovery path and can interrupt federated reads.
Recovery should use a compatible forward revision. This does **not** waive
current security checks, CI, branch protection or operational monitoring.

## Verification and deployment

Prove in tests: exact read/write wire shape; rejection of scoped legacy requests
before dispatch; receiver capability fail-closed; no read-to-write escalation
when declarations change; public bearer authorization; per-node and multi-node
routing. Confirm live provider capabilities and read calls before release.

Normal PR CI validates the final HEAD. The existing repository main-push
deployment pipeline may update gway-001 and Watchtower after merge; merge alone
does not prove runtime activation. Validate deployment independently.

Related: #586, #591, #595.
