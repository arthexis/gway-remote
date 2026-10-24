# GWay-001 private MCP tunnel (read-only M2)

This is **single-host** integration for GWay-001, not a multigateway design.
The MCP server from M2 stays on `127.0.0.1:8770/mcp`. The official
[openai/tunnel-client](https://github.com/openai/tunnel-client) polls the
OpenAI control plane over outbound HTTPS. No public DNS, Nginx route, SSH,
WireGuard port, or Agent Ops dispatch tool is required.

## Prerequisites

1. Confirm M1/M2 code and Agent Ops adapter are installed on GWay-001.
2. Install the supported **official** `tunnel-client` binary using its published
   release/install guide, then verify `tunnel-client --version`. Do not
   download unpinned binaries from third-party hosts. Ensure it is available in
   the user systemd service PATH (systemd may not inherit interactive PATH).
3. Run `sh scripts/install-mcp.sh` if necessary. Its Python package preflight
   must pass. Confirm its `mcp.env` mode is 0600; never reveal its token.
4. Create a tunnel ID in OpenAI Platform Tunnels, associate the intended
   ChatGPT workspace, and obtain a **runtime** API key with Tunnels Read + Use.
   Do not use an admin key as the persistent runtime key.

## Opt-in setup

Run `sh scripts/install-mcp-tunnel.sh` **as the service operator**.
It only installs a user unit and wrapper, creating an empty credentials
template if absent. Fill `~/.config/gway-remote/tunnel.env` locally:

```ini
CONTROL_PLANE_TUNNEL_ID=tunnel_... 
CONTROL_PLANE_API_KEY=...
```

The installer does not print, overwrite, upload, or auto-enable credentials.
Keep the config directory mode 0700 and both env files mode 0600.
Never commit these files or pass secrets via ChatGPT, CLI flags or logs.
`gway-run-mcp-tunnel` injects the existing M2 Bearer token *only* into local
MCP request and discovery headers; `CONTROL_PLANE_API_KEY` is used by
the official client for outbound OpenAI authentication.

Confirm local read-only MCP responds using existing private validation steps.
Validate the official client configuration (`tunnel-client doctor` with
the appropriate environment from the private env files). Then, explicitly:

```sh
systemctl --user enable --now gway-remote-mcp.service
systemctl --user enable --now gway-mcp-tunnel.service
systemctl --user status gway-mcp-tunnel.service
```

The second service depends on the first. Check `127.0.0.1:8771/readyz` and
the local tunnel-client health UI. Then add a custom ChatGPT MCP connection
by selecting the **verified tunnel** in Plugins. Validate `agent_status`,
`agent_list_issues`, `agent_preview`, and `agent_observe` through ChatGPT
without invoking Codex. A tunnel existing in Platform is not proof that it
is associated with the correct ChatGPT workspace or connected.

## Restrictions and failure behavior

- **No submit capability**. The M2 contract remains read-only.
- Do not expose localhost 8770/8771 externally; no firewall opening.
- If the tunnel or local MCP is unreachable, queries fail, not queue for later
  execution. Never retry a future mutating operation with a new identity.
- Local service credential rotation requires restarting both services after
  replacing the local token; runtime-key rotation restarts the tunnel service.
- No CI on main; review/test this installer through PR CI only.
- The wrapper uses `MCP_EXTRA_HEADERS` and
  `MCP_DISCOVERY_EXTRA_HEADERS` from the official client configuration.
  Verify in a supervised field test that these headers survive the connector
  request path. If a connector-provided Authorization header overrides the
  static local header, fail closed; do not weaken M2's Bearer requirement.
- The tunnel-client's environment is deliberately limited to the service
  account and may be inspectable by that same operator. Avoid debug tracing.
- Note that `systemd --user` might require lingering for startup at boot.
  Enable lingering only with operator approval.

Official documentation:
- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://github.com/openai/tunnel-client/blob/master/docs/configuration.md
