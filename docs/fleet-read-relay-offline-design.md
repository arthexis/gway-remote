# Fleet v1: dormant read-only SSH relay design

This is a **source-only offline design**, not an installed identity or a live authorization guarantee.

## Trust boundary

The existing `gway-relay` key, sshd `ForceCommand`, and `node_exec_protocol` remain unchanged for Odoo/AgentOps and legacy execution. A future, separate **root-managed read-only SSH identity and private key** must use a distinct `Match User` / `ForceCommand` bound to `python3 -m gway_remote.node_read_protocol`, with no shell, forwarding, PTY, password authentication, user-controlled command, or sudo beyond that fixed entrypoint. Its Watchtower-side transport must independently pin the enrolled host key and read identity. No such key, account, manifest, sudoers, or SSH configuration is created by this PR.

The read-only entrypoint calls the same bounded JSON receiver with a fixed, caller-independent operation policy: `provider_list` and `provider_read_call` only. The node itself forces `trusted_scope=read`; `provider_call` (including legacy `authorized_scope=execute`), `submit`, `cancel`, `result`, and `limits` are denied before provider discovery or job execution. The request cannot select or widen the operation policy. The existing execution entrypoint retains backward compatibility.

## Offline acceptance

- Read identity: allow only discovery and read call; deny legacy execute, arbitrary job operations, extra scope fields, wrong node, and caller-supplied policy.
- Watchtower: authenticate bearer read scope before dispatch; use a distinct enrolled, pinned SSH identity for read; verify response node and request ID.
- Fleet: validate authoritative inventory provenance, unique node IDs, identity attestation, timestamp and bounded size before dispatch; reject stale, malformed, oversized UTF-8 or ambiguous provider responses; isolate per-node failures.
- Existing execute identity: preserve current Odoo/AgentOps behavior and tests.
- Deploy acceptance **not met**: separate read key/account/sshd/sudoers/transport configuration and actual attested node installation have not been implemented or verified. The diagnostics provider has no confirmed installed root-owned manifest. No production access is authorized here.

This is a defense-in-depth proposal: the legacy relay still accepts caller-supplied execute scope on its own authenticated SSH channel, so compromise of that existing credential remains a distinct risk.

## Watchtower transport audit (not integrated)

`ProviderTransport.invoke` currently delegates both trusted_scope=read and execute to `pinned_transport(self.execution_transport, node)`. `MultiNodeTransport` and `PinnedNode` select one enrolled transport per node; there is no separate read-only SSH key/remote_user selection or verified mapping of the read-only forced command. Consequently the dormant `node_read_protocol` is **not reachable from Fleet** as a distinct authenticated identity. Merely selecting `provider_read_call` in a payload does not prove peer-level least privilege.

An eventual offline integration must inject two independently pinned transport inventories (read and execute), route `provider_list` and read `provider_call` only to the read identity, reject any fallback from read to execute, and keep execute calls on the existing authenticated relay. Negative tests must cover absent read enrollment, wrong host key, wrong SSH principal, stale attestation, wrong-node replies, request-ID replay, and denial of execute on the read transport. No such routing is claimed here; do not activate or install the read identity until reviewed.

## Optional source-only transport selector

`ProviderTransport(execution_transport, read_transport=..., require_read_identity=True)` now routes read calls to the explicitly supplied pinned read transport, and execute calls to the existing execution transport. In strict mode a missing read transport fails closed; a configured read transport must use both a different SSH principal and a different private identity file from the execute transport. The existing constructor remains backward-compatible (non-strict) for legacy Odoo/AgentOps; **Fleet/Watchtower does not yet construct this strict selector**, so this is not a deployed separation guarantee. Both transports still rely on the existing `PinnedNode` host-key validation and node-scoped lookup. No private keys, enrolled read nodes or production policy were created.

## Follow-up audit of CI 42672115617 and selector (2026-11-09)

The GitHub workflow record reports terminal **failure** for commit `5409dbf7`, but its jobs API returns `total_count: 0` and the commit check-runs API also returns zero entries. The failing job and logs are therefore not available from these interfaces; do not mark this commit accepted or guess the failure. No retry or production changes were made.

**Additional acceptance gaps**: `ProviderTransport` currently checks different SSH principals and key paths only when a read transport is explicitly injected; this does not cryptographically prove that the keys differ. It also does not verify that the two pinned identities refer to the same attested endpoint/host-key fingerprint, nor that the read identity is enrolled and bound to the read-only ForceCommand. The strict constructor is not instantiated by the Watchtower federation coordinator. An injected `MultiNodeTransport` can be resolved per node, but its read enrollment must be independently authenticated. Existing response validation checks exact `node` and `request_id`; SSHTransport separately validates host-key pin, request size and timeout. Tests still needed with real temporary PinnedNode files and multi-node routing to demonstrate these checks together. Do not activate the strict selector until these conditions are met.
