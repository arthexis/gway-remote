# MCP Source Aggregation v1 — Increment A: verified topology and contract

Tracking issue: #373. **This increment is documentation only**: no OAuth, relay, runtime, Ansible, executor, or fleet changes.

## Evidence and limitations

Read-only review of the repository's `main` branch, and the actual `gway-001` host via the existing GWay Remote `node_exec` pathway, on 2026-11-04.

* On `gway-001`, `gway-remote-mcp.service` is **active** in the `arthe` user systemd manager and invokes `/usr/bin/python3 -I /opt/gway-mcp/releases/94a7d067368174ed34aea890398dab6964fe6c14/run.py mcp_http`. Its user service file is `/home/arthe/.config/systemd/user/gway-remote-mcp.service`. The host's `python3 --version` is **3.11.2**. It has no importable `mcp` SDK in the command's default Python environment. The operator executor doesn't export a user bus by default; explicit `XDG_RUNTIME_DIR=/run/user/1000` and `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` enabled the read-only `systemctl --user show` query. These are observations, not instructions to change the executor environment.
* The private app implementation is `gway_remote/mcp_http.py` -> `gway_remote/mcp_agent.py`, exposing **seven** read-only Agent Ops/GitHub tools via `tools/list` and `tools/call`. It supports single-message, JSON response Streamable HTTP and no SSE or sessions; `mcp_http.py` is the existing private transport. `mcp_agent.py` uses a fixed registry of names/handlers. The user service uses a private bearer and loopback-only listener.
* The Watchtower-side gateway, `gway_remote/mcp_bearer_gateway.py`, already aggregates results: after forwarding `tools/list` to the private backend it appends Watchtower-owned `node_list`, `node_capabilities`, `node_exec_preview`, and execution/deployment tools. Tool execution for these Watchtower-owned tools is handled **locally on Watchtower**, not sent to `gway-001`. Private read-only tool calls are forwarded to `gway-001` through the fixed upstream, and an explicit `ALLOWED_TOOLS` allowlist currently rejects new names. Its merged tool descriptions get read/execute OAuth security metadata.
* The configured Watchtower relay unit `deploy/mcp-bearer/gway-mcp-private-bridge.service` forwards `127.0.0.1:19011` to `127.0.0.1:8770` on the authenticated SSH target across the private transport. The gateway unit `deploy/mcp-bearer/gway-mcp-gateway.service` listens on loopback port 19010, forwarding to 19011; `gway-mcp-link.service` is a **separate OAuth-linking process** under a distinct identity, not the private tool server. These locations are confirmed from **repo unit files**, not direct privileged Watchtower runtime inspection.
* Existing `mcp_http.py` uses MCP protocol versions `2025-03-26` and a compatibility path for `2026-07-28`; Watchtower adapts newer client requests/results for the older backend. No new aggregator may silently break these negotiations, output wrappers, or auth challenges.
* Existing developer documentation may describe pre-M2 deployment stages; prefer the current source and live unit observations over older rollout prose. No live privileged Watchtower systemd inspection was performed in this audit.

## Key conclusion: already an aggregator, but split across two hosts

The intended split is real: the **private MCP app lives on 001** and **Watchtower is the authenticated relay/edge**. However, Watchtower is **not a byte-for-byte dumb proxy**: it performs OAuth, node-tool composition, strict tool allowlisting and dispatch for Watchtower-local commands. Consequently, adding a stdio MCP provider only to `mcp_agent.py` would NOT make its tools invocable from ChatGPT: Watchtower's `ALLOWED_TOOLS` gate would deny the new tool name. V1 must extend this existing allowlist/authorization integration **without introducing another endpoint or independent source-policy database**.

## Proposed V1 interface boundaries (for increments B–F)

1. **Private source layer on gway-001**: `mcp_agent` delegates optional tools to an isolated stdio source adapter with `initialize`, `tools/list`, and `tools/call`. Existing built-in handlers remain unchanged. No FastMCP server dependency.
2. **Trusted source registration**: operator-approved installed release only, pinned commit/version, fixed absolute executable argv, namespace, approved runtime OS identity, limits and **read-only permission ceiling**. A repository's self-declared MCP tools or `readOnlyHint` never grant permissions. Sources not explicitly allowed remain invisible and non-callable. Registration/discovery must not rely on caller-supplied paths, URLs or arbitrary shell.
3. **Names**: stable, unambiguous namespaced tool identifiers (e.g. `odoo__sales_latest`); built-in names are reserved. Reject duplicates, invalid schema/description and source changes during dispatch. Keep deterministic listing.
4. **Watchtower cross-boundary authorization**: avoid a separate manually maintained name allowlist per tool; use a **bounded, authenticated export of already approved tool names/metadata** from the private backend or release-pinned provisioning evidence, and verify the same source identity/permission in the gateway before forwarding `tools/call`. Never allow arbitrary names on the grounds that the backend advertised them. Upstream tool text is untrusted; source-specific authorizations require explicit operator policy. Do not give execute scope to new tools merely because a user has `gway:execute`; **v1 sources are read-only only** and require read entitlement. Do not expose Watchtower-local tools as source-provided names.
5. **Transport**: preserve the single public MCP URL, Watchtower OAuth/linking, current bridge and backend bearer. Preserve bounded request/response sizes and version negotiation. No SSE or dynamic notification support can be assumed on current stateless transport; **v1 discovery may require explicit connector/tool refresh**. Live notifications are deferred unless separately proved compatible.
6. **Lifecycle**: enabled registration tied to a verified active release and its rollback; unavailable source is removed from invocation, with bounded failure isolation, process cleanup and auditable status. Avoid modifying the existing app's process or service runtime in v1 unless a later acceptance gate requires it.
7. **Protocol contract**: use structured JSON-RPC request/response and standard MCP tool schema/result representations; validate sizes, `isError`, and permitted content types. For first pilot, handle bounded text/structured JSON tool results only; reject/normalize unsupported capabilities explicitly. Child server sees neither the public OAuth token nor Watchtower credentials.
8. **Executors and Ansible**: none of the current `node_exec`, SSH forced commands, user identity or concurrency settings may be widened to make source aggregation work. Deployment activation of source config should be opt-in, idempotent and constrained to the existing release mechanism, not an independent configuration controller.

## Proposed increments and gates

- **B: registry and pure composition tests.** Models/source configuration + namespaces, strict read-only validation and collision handling, all in tests without a subprocess or production service.
- **C: bounded stdio client on 001.** Protocol handshake/list/call, timeout/process cleanup, source isolation; test a synthetic source. Assess optional client SDK in isolation if custom protocol code becomes larger than adopting a supported library.
- **D: private/backend + Watchtower integration.** Wire the backend's source registry into `mcp_agent` and extend Watchtower authorization gate via verified approved-source names, without weakening its deny-by-default behavior or changing OAuth. Tests prove existing tool list and tool calls remain compatible.
- **E: `odoo-gelectriic` pilot.** One read-only MCP stdio tool driven by its existing Bastion-backed Odoo API client, release-pinned to gway-001; no new endpoint or credential store.
- **F: field acceptance.** Live ChatGPT discovery/call, source failure/disabling/rollback, OAuth token reuse, and regression tests for Watchtower tools, node executor and legacy private tools.

### Tests required before non-documentation changes

* Golden snapshot of the original seven private tools plus Watchtower's node/deployment tools; verify tool descriptions and calls remain compatible.
* Negative tests: unregistered source, name collision with built-ins, malformed schema, read-only annotations spoofed, oversized list/result, malicious stdio process, backend downtime, stale/changed release, and unauthorized tool call directly to Watchtower.
* A read-only source must remain unavailable to invocation even if a malicious backend advertises it but operator policy has not approved it.
* Test both protocol compatibility paths and OAuth scope challenges, including the one-token operator flow.
* Verify on the supported host Python versions and existing Ansible syntax-check setup; do not add unrelated Android, OCPP or node deployments.

## Decision gate

**A complete:** topology and risk documented. **B may proceed** without touching production. Before D, design and test the cross-host approved-tool authorization handshake; simply appending names to `ALLOWED_TOOLS` or accepting arbitrary backend tool names is not an acceptable final implementation.
