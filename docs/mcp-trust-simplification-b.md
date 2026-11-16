# Issue #586 — Stage B/P1: unscoped execute RPC emission

This increment is a **Draft-only partial Stage B**, not permission to merge or
deploy and not final retirement of internal OAuth-related scope parameters.

## Behavior
- Watchtower still authenticates the caller and applies `gway:read` /
  `gway:execute` on the public endpoint.
- `ProviderTransport.invoke` continues to receive a *gateway-derived* scope
  during transition. For `execute`, it no longer serializes
  `authorized_scope` in SSH `provider_call`.
- `read` requests still serialize legacy `authorized_scope="read"`.
  The downstream provider verifies that the *live tool declaration* is still
  read-only before calling it. This is a temporary operation-classification
  race guard, not a second authentication of an OAuth token.
- The pinned SSH sender now accepts **both exact** field sets. It continues to
  reject extra/missing fields, unexpected nodes and invalid request IDs.
- Stage A already made `node_exec_protocol.serve_one` compatible with both.
  Existing node-side catalog and registration validation remains.
- No new key, Linux identity, SSH config, Ansible, provider privilege or network
  endpoint is introduced.

## Stage B/P2: one route snapshot per admitted request

- Watchtower verifies public OAuth against the tool classification returned
  by one `federation.discover()`. The same authenticated routing snapshot is
  passed to `federation.call(..., routes=routes)`, eliminating the second
  `provider_list` round trip within a single federated tool invocation.
- This reduces unnecessary transport dependence and prevents a second
  discovery from disagreeing with the admission decision.
- The node still discovers the live tool when dispatching. Legacy read
  requests keep their node-side write guard; a read-to-write change is not
  permitted by the transport just because the gateway has cached a route.
- This **does not restore** missing providers when the first discovery is
  empty or its underlying node is unavailable. Operational issue #591
  diagnoses that separately.
- No added OAuth identity propagation, keys, node users, transports or
  external endpoints. Standalone federation calls without a supplied
  snapshot retain their existing discovery behavior.

## Stage B/P3: read-only node operation, without OAuth fields

The receiving SSH protocol now recognizes `provider_read`, with the same
exact `node`, `request_id`, `provider`, `tool`, and `arguments`
fields as an unscoped `provider_call`. It **does not** accept
`authorized_scope`. This is an operation contract: the owning node must
confirm that the live tool is still read-only before invoking it. It reuses
the existing provider registry and stdio read/write verification, with no
new identity, SSH key, service or authorization framework.

During P3 the sender used legacy `provider_call` with `authorized_scope="read"`.
P4 now switches automatically **only for receivers advertising support**;
older nodes continue to use the legacy read wire without an unsafe probe.

This operation-bound check is not OAuth verification. Public OAuth remains
at Watchtower. Tests prove allowed reads, rejected writes, precise wire
fields and node identity without real SSH or providers.

## Stage B/P4: capability-based read emission and rolling compatibility

A P3-or-newer node advertises `supports_provider_read: true` **on its
provider_list provider records**. This optional, provider-level field is
ignored by the old Watchtower parser and is a version/capability indicator
rather than a credential. It can only come from the authenticated node
catalog. Its absence, or explicit `false`, means the receiver might be
older and requires the existing legacy `provider_call` with
`authorized_scope="read"`. Malformed capability values fail closed.

After public OAuth admission, Watchtower uses its single authenticated
discovery snapshot to choose:
- **read + advertised support** -> `provider_read` with no scope field;
  the receiver confirms the live tool is still read-only before calling it
- **read + no support** -> legacy `provider_call` with scoped read;
  the old receiver still blocks write reclassification
- **execute** -> unscoped `provider_call`, as introduced in P1

This supports receiver-first rollout in **one PR**: gway-001's installed
receiver can gain support before Watchtower starts using it. Old Watchtower
ignores the optional provider metadata; new Watchtower falls back when
encountering older nodes. No new service, extra query, deployment flag,
user account, OAuth identity propagation or registry is needed.

**Deployment gate:** Stage A receiver was installed by automatic workflow
#43819904323, and a subsequent live AgentOps status/read check succeeded.
For this PR, verify the existing deploy sequence activates the node runtime
before the Watchtower gateway, and stop instead of activating a sender whose
receiver is not supported. Do not infer installed runtime from PR CI alone.

## Why old receivers still require a legacy read fallback

P2 removes the repeated Watchtower discovery, but the registered tool can
still change classification before the node dispatches it. P3 introduced a
read-only operation bound to the receiver's live provider declaration. P4
selects that operation only when the node advertises its support. For an older
node the existing legacy read request retains the same live-declaration
write-denial behavior. Neither path carries a caller-chosen privilege
escalation, and neither invents an additional OAuth authority.

The target architecture is **public OAuth admission at Watchtower plus actual
operation validation by the node**, with a temporary legacy read wire for
mixed revisions only. Once receivers converge, Stage C can remove that
compatibility code; no new service or framework is necessary.

## Stage C acceptance boundary

- Current deployed scope-free RPCs use `provider_read` for supported node
  reads and unscoped `provider_call` for execute, with legacy scoped-read
  fallback only for older receivers. Public `gway:read` must never invoke
  a tool that is currently write-classified.
- `/opt/gway-mcp/previous` may point to a pre-B immutable release and the
  node/gateway restore independently. No compatible rollback floor has been
  established, so deletion of the fallback remains **out of scope**.
- No new CI or deployment is implied by accepting the compatibility
  decision. The private backend's `X-Gway-Caller-Scope` and the unused
  `FederatedAuthContextV1` codec are separate boundaries; this policy
  does not authorize changing either one.
- Future removal requires a separately approved B-or-newer minimum for
  receivers and rollback, explicit per-provider capability evidence and
  adversarial mixed-version regression. Avoid periodic reaudits without
  a material change.
- Issue #586 remains open until its revised acceptance/closure is explicitly
  authorized; issue #591 and AgentOps #80/#81 remain separate.


## Stage C legacy-wire retirement candidate — not active

Following a new explicit owner request, the Draft candidate eliminates the
remaining `authorized_scope` field from the **SSH provider RPC**, not public
OAuth admission or the private backend's separately scoped HTTP path.
Read-only tools dispatch exclusively as `provider_read`; writes use unscoped
`provider_call`. If the authenticated node catalog does not advertise
`supports_provider_read=true`, read calls fail closed **without invoking the
node**. A legacy Stage A Watchtower that transmits scoped `provider_call`
to a C receiver is rejected before provider discovery. Thus no read call is
silently upgraded to write privilege.

**HARD activation gate:** immutable Stage A releases are still candidates for
node or Watchtower rollback; the two ends can be restored independently. C/A
mixes can therefore lose availability although they fail closed. Before Ready,
merge or automatic deploy, prove a minimum B-compatible rollback revision for
both ends (including operator recovery), observe the installed raw capability
per available provider, and accept the adversarial A/B/C matrix. Do not
interpret this Draft or CI as a live runtime or rollback guarantee.

The existing #586/#592 A/B compatibility decision remains the current
operational contract pending separate activation acceptance. No AgentOps,
SSH/account, Ansible, public OAuth or private `X-Gway-Caller-Scope` changes
are part of this code candidate.
