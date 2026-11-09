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

## Explicit pinned-SSH construction boundary

Optional `require_pinned_ssh=True` requires `require_read_identity=True` and exact `SSHTransport(PinnedNode)` objects (including each member of `MultiNodeTransport`) for both inventories; rejects duck-typed offline doubles at construction and rechecks selected transport at dispatch. Offline tests retain default support for doubles. Watchtower does **not** opt into this setting; future construction must independently verify enrolled and attested read identities, distinct real key material and ForceCommand, before enabling it. It must not silently fall back to the legacy execute identity. The current source-only checks are not a proof of deployed security.

## Verified Watchtower construction point and acceptance (2026-11-09)

CI workflow `42717312694` for `adb455aa`: terminal **SUCCESS**, 11/11 checks. Exact production wiring point: `gway_remote/mcp_bearer_gateway.py`, `main()`, around lines 746-754. It calls `load_service()`, takes `execution.relay.transport`, then constructs `FederatedProviders(transport=ProviderTransport(transport), nodes=...)`. `gway_remote/watchtower_exec_service.py` builds the execution `SSHTransport(PinnedNode)` inventory and `MultiNodeTransport`; **there is no separately attested read inventory at this construction point**.

Safe future integration design, NOT enabled: obtain an independently verified read inventory of `SSHTransport(PinnedNode)` from trusted node enrollment with distinct SSH principal and private key, matching host pin and node ID; require documented read-only ForceCommand binding; then inject `ProviderTransport(execution_transport, read_transport=read_inventory, require_read_identity=True, require_pinned_ssh=True)`. If read inventory is absent or invalid, fail closed for read calls, never substitute execution transport. Preserve existing execution relay for Odoo/AgentOps. Do not source identity, host, key, scope or node from RPC arguments. Validate each node's attestation before making it available to the federation.

Current tests validate exact pinned transport classes, temporary known_hosts/private file permissions, host fingerprint, same endpoint, node/request_id correlation, timeout and multi-node no-fallback. This is **offline acceptance only**; separate read key, real attestation, ForceCommand and installed diagnostics manifest remain unverified. No Watchtower activation, SSH/Ansible production changes, credentials or deployment.

## Why Watchtower construction is not enabled

`watchtower_exec_service.load_service()` authenticates execution inventory using `node_registry_inventory.load()` and requires `execute_eligible`, registered, identity_verified, reachable and matching pinned address. Those checks attest **execution eligibility**, not an independently enrolled read-only SSH principal or forced-command binding. The repository does not yet provide a trusted read-inventory loader with evidence for an installed read-only ForceCommand; therefore introducing a runtime constructor toggle or accepting a caller-provided `read_attested=True` boolean would be an unsafe trust bypass. The existing `mcp_bearer_gateway.main()` constructor remains untouched. A future read loader must validate a root-owned configuration, host fingerprint, private-key file mode, distinct principal/key material, and independently authoritative read enrollment plus node-side forced-command receipt. It must fail closed if any evidence is absent and never reinterpret execute_eligible as read eligibility. Tests cover mixed-trust MultiNodeTransport members and injected scope, but cannot establish live read attestation without that loader.
