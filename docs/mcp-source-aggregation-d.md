# MCP source aggregation — Increment D (D1 + D2)

This branch adds both integration surfaces in one PR, tracked by #373.

## D1 — private backend

`mcp_agent.configure_sources(registrations, approved_catalogs)` composes approved
namespaced read-only source tools and dispatches them via the bounded stdio
client. Default registration is empty and preserves the existing tool contract.
This API must be called only by a trusted release-pinned provisioning layer;
the MCP client cannot submit registrations.

## D2 — Watchtower

`make_server(..., approved_sources={name: exact_tool_declaration})` accepts
an operator-provisioned, trusted catalog. Calls to federated names are denied
unless explicitly approved; discovery filters out unapproved upstream names.
A mismatch between approved and advertised declarations fails closed.

## Remaining activation gate

The code deliberately does **not** load an operator policy file, enable
sources from environment variables, or alter systemd/Ansible. Before live
activation, add reviewed provisioning of the same approved catalog on both
hosts with release identity verification, atomic rollout/rollback, and
authenticated end-to-end discovery/call tests. Never populate policy from
untrusted upstream discovery or a caller-supplied path. No production sources
are enabled by this PR.

## Cross-host provisioning contract (new)

Both `mcp_http.serve()` on gway-001 and `mcp_bearer_gateway.main()` on
Watchtower accept the same opt-in environment variables:

- `GWAY_MCP_SOURCE_POLICY=/etc/gway-mcp-gateway/sources.json`
- `GWAY_MCP_SOURCE_POLICY_SHA256=<sha256 of exact policy bytes>`

The file must be a regular root-owned, non-group/world-writable file, not a
symlink, with at most 64 KiB. It contains `{"version":1,"sources":[]}` by
default. Each source has `registration` (source_id, full revision SHA,
absolute executable, fixed argv, run_as, enabled, permission=read) and
`tools` (approved tool declarations). The two processes independently
verify the exact same digest and reject invalid or incomplete configuration.
No environment variables means no external sources.

**Operator rollout:** stage identical bytes on both hosts using the existing
privileged provisioning channel, verify the digest on both, update the
protected service environment files with the same pinned digest, restart the
private backend first and Watchtower gateway second, and validate OAuth
`tools/list` plus `tools/call`. Roll back both to empty policy on failure.
The deploy workflow does not yet perform these cross-host copy/restart steps;
production activation must wait for a reviewed automation and field smoke.

A policy declaration is **not** proof of the installed executable's release
identity. The operator must verify the SHA-pinned source installation and
service OS identity before enabling it. No source is enabled by this PR.
