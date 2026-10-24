# ChatGPT MCP integration — M1

This change implements a **transport-independent, read-only MCP tool core** for
Gway Remote Agent Ops. It is intentionally **not** a public MCP server and cannot
yet be installed as a ChatGPT plugin.

## Tool contract

- `agent_list_issues` → canonical allowlisted Agent Ops issues; no arguments
- `agent_status` → current admission state; no arguments
- `agent_preview(ref)` → trusted issue preview
- `agent_observe(ref, at)` → timestamp-keyed existing invocation state, including
  persisted provenance when supported by the installed Agent Ops version

`gway_remote.mcp_agent.list_tools()` returns the MCP-oriented definitions and
`call_tool(name, arguments)` delegates only to existing fixed read-only
`agent_ops_adapter` functions. No new repository registry, queue, execution
executor, secret store, or shell entry point was introduced.

## Non-public security boundary

Before connecting ChatGPT, the next increment must implement a supported,
authenticated MCP transport with HTTPS/TLS and host/operator access controls,
confirm how that transport reaches the private Gway-001 API without exposing
it publicly, and package a private plugin. Do not bind the current Mobile API
to a public address or reuse its bearer secret in prompt text.

The eventual `agent_submit` must be a separate, explicitly authorized
increment and must preserve exact UTC request identity, label/trust checks,
single-slot dispatch, and server-derived provenance. It is deliberately
absent from this module. CI runs only on PRs.

## Local development

```python
from gway_remote.mcp_agent import list_tools, call_tool
print([tool["name"] for tool in list_tools()])
# call_tool("agent_status", {})  # needs installed Agent Ops
```

All entrypoints in this increment are library functions, **not an externally
reachable server**.
