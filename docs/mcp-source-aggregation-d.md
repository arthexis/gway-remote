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
