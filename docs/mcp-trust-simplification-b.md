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

The sender still uses the legacy `provider_call` + `authorized_scope="read"`
for read operations **until the P3 receiver is activated**. Do NOT switch
read emission in this PR increment: the deployed Stage A receiver does not
recognize the new verb. The next P4 increment may switch the sender after
a separately authorized receiver deployment is confirmed.

This operation-bound check is not OAuth verification. Public OAuth remains
at Watchtower. Tests prove allowed reads, rejected writes, precise wire
fields and node identity without real SSH or providers.

## Why read requests remain legacy in this increment

The public gateway checks a dynamically discovered provider route; the
federation call discovers the route again, and the node re-discovers its live
tool declaration. A tool's classification can change between these steps.
Unconditionally removing the read-vs-write assertion from all three layers
would let a valid read-only bearer reach a write if such drift occurs.

The intended final state is **OAuth authorization at Watchtower and operation
validation at the node**, without repeated OAuth claims. Finish the read
migration only after guaranteeing that a previously admitted read operation
cannot become a write between admission and dispatch, without recreating a
federated identity framework. A stable operation contract/version or equivalent
minimal solution must be reviewed separately.

## Preconditions and acceptance

1. Confirm Stage A receiver is deployed on every target before activating this
   sender. A merged commit or successful GitHub CI is not deployed-node proof.
2. Run the existing public OAuth read-denied/execute-allowed regressions and
   provider catalog/stdio tests unchanged.
3. Hermetic tests: execute emits no scope; legacy read retains its scope;
   pinned transport accepts only two exact `provider_call` shapes and
   rejects malformed requests without invoking SSH.
4. No manual workflows, AgentOps, nodes or deployments during Draft review.
5. Stage B/P2 and Stage C must retire the remaining legacy path after resolving
   the classification drift case and confirming deployment compatibility.

Keep issue #586 and AgentOps #80/#81 open. Do not merge this Draft until the
post-merge Stage A deployment and receiver compatibility are established.
