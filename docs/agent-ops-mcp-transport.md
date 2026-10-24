# Agent Ops MCP — M2 transport (private preview)

M2 introduces a **sessionless MCP Streamable HTTP JSON-RPC transport** for
the four M1 read-only tools. It does **not** publish a ChatGPT plugin, deploy a
public gateway or expose a mutation/submit tool. PR #234 must merge first;
this PR is based on its branch to keep increments separate.

## Local smoke test

Generate a private random token securely and inject it through the process
environment, without committing it or displaying it. Run:

```sh
GWAY_MCP_BEARER_TOKEN="<secret-from-secure-credential-store>" python3 -m gway_remote.mcp_http
```

The listener is restricted to `127.0.0.1:8770`, POST `/mcp`. An absent
token prevents startup. Requests require `Authorization: Bearer <token>`.
Cross-origin browser requests are rejected; nothing is discoverable anonymously.
There is deliberately no connection from the internet to this listener.

Methods: `initialize`, `notifications/initialized`, `tools/list`,
`tools/call`. Only `agent_list_issues`, `agent_status`, `agent_preview`
and `agent_observe` can execute. The existing canonical repository allowlist
and Agent Ops trust checks remain in the downstream adapter.

## Remote ChatGPT plugin: pending integration

A remote ChatGPT connection additionally requires an operator-authenticated,
TLS-terminated **Streamable HTTP MCP endpoint**, with verified private routing
to this listener, compatible token/OAuth authentication for the ChatGPT
connection flow, origin protections and credential rotation procedures.
The current endpoint deliberately remains loopback-only. Do not install a
public Nginx location or copy bearer credentials into a prompt, URL, README
example, screenshots, or logs.

A future private plugin must reference the verified HTTPS `/mcp` URL; this
code alone cannot be connected remotely. Confirm the hosting network and
ChatGPT-supported auth scheme before rollout. No Gway-001 API or port should
be exposed directly. `agent_submit` belongs to M3, with approval and
server-derived provenance.

## Limitations

This minimal transport handles JSON requests and does not implement server-
initiated notifications, streaming SSE or session tracking. Validate actual
client interoperability before declaring the plugin installed. No production
deployment is authorized by this documentation.
