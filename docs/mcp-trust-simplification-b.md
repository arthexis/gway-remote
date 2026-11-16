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

## Preconditions and acceptance

1. Confirm Stage A receiver is deployed on every target before activating this
   sender. A merged commit or successful GitHub CI is not deployed-node proof.
2. Run the existing public OAuth read-denied/execute-allowed regressions and
   provider catalog/stdio tests unchanged.
3. Hermetic tests: execute emits no scope; legacy read retains its scope;
   pinned transport accepts only two exact `provider_call` shapes and
   rejects malformed requests without invoking SSH.
4. No manual workflows, AgentOps, nodes or deployments during Draft review.
5. Stage C removes the remaining legacy read wire only after all deployed
   receivers advertise `supports_provider_read` and rollback is safe.

Keep issue #586 and AgentOps #80/#81 open. Do not merge this Draft until the
post-merge Stage A deployment and receiver compatibility are established.
