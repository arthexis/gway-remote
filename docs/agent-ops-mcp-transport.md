# Agent Ops MCP — M2 private, read-only transport

This increment implements a **sessionless MCP Streamable HTTP** server for the
four M1 read-only tools. The endpoint is only bound to `127.0.0.1:8770`. No
public listener, internet route, operator credentials, ChatGPT plugin connection
or Agent Ops dispatch capability is created by this PR.

## Installation: opt-in, non-root

The installer is **not** invoked during deploy automatically.

1. Install Gway Remote into the Python environment used by `/usr/bin/python3`.
2. Run `sh scripts/install-mcp.sh` as the Gway Remote operator (not root).
3. Confirm the generated `~/.config/gway-remote/mcp.env` is mode 0600 and the
   directory is 0700. Never print or commit the secret.
4. Inspect `systemctl --user cat gway-remote-mcp.service`, then explicitly
   run `systemctl --user enable --now gway-remote-mcp.service` when ready.
5. Verify listener bound only to loopback and a no-token POST returns 401.
   Use an authenticated request **without logging the token** to test
   `initialize`, `tools/list` and a read-only invocation.
6. Rotate the token by stopping the service, replacing the secret file with a
   freshly generated token, then restarting the service and updating its
   authorized gateway client. Never reuse the Mobile API token.

## Protocol

- POST `/mcp`, `Content-Type: application/json`, and `Accept:
  application/json, text/event-stream`.
- Protocol version `2025-03-26` (other explicit versions are rejected).
- `Authorization: Bearer <private-token>` on every request.
- No incoming browser `Origin` values accepted; this is a machine-to-machine
  endpoint and is not a browser-facing CORS API.
- Single JSON-RPC request or notification per POST. Notifications return HTTP
  202. Responses are `application/json`; no SSE streaming or session support.
- GET `/mcp` returns 405 (no SSE listener).
- Maximum request body 64 KiB; arbitrary tools, malformed parameters, and
  mutating operations are denied.

Read-only tool names: `agent_list_issues`, `agent_status`,
`agent_preview`, `agent_observe`. The downstream adapter injects the
canonical repository allowlist; do not create a separate environment allowlist.
No arbitrary shell commands, GitHub edits, Codex launches or deployments are
exposed through this transport.

## What remains before a working ChatGPT plugin

ChatGPT cannot reach a loopback-only Gway-001 server from a remote plugin.
The **next deployment/integration step** requires verifying a real externally
reachable HTTPS MCP endpoint, choosing an authentication scheme supported by
the actual ChatGPT connection flow, and confirming its gateway can securely
reach Gway-001 across the authenticated private network. Never publish this
port, add a wildcard Nginx proxy route, or expose the existing private Mobile
API to the internet. Do not write a plugin manifest with an invented URL.

Only after a verified HTTPS MCP URL exists should a private plugin package
reference that exact endpoint in `mcp.json`, be connected with user-authorized
credentials, and tested from ChatGPT. Plugin creation does not configure
the gateway or prove end-to-end tool accessibility.

M3 adds `agent_submit` separately with explicit human approval and
server-derived provenance. All checks run on PRs, not on main.

## Limitations

This transport is deliberately minimal. It implements a subset of the
Streamable HTTP protocol suitable for single JSON-RPC messages and read-only
tools; it does not implement batches, streaming, session resumption, SSE or
OAuth/OIDC. Validate the actual connected client's interoperability before
claiming a successful plugin installation.
