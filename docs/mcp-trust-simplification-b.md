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
