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
