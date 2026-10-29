# M2.1 private deployment runbook

The Watchtower gate remains separate from main deployment. The stage script
creates restricted Linux users/groups and directories and installs an inert
systemd unit. It does not start/enable the service or modify Nginx.

## Preconditions
- Confirm the package is importable by /usr/local/bin/python3.
- Independently configure and verify host-identity-pinned private forwarding
  from Watchtower 127.0.0.1:19011/mcp through WireGuard/SSH to gway-001
  127.0.0.1:8770/mcp. This PR does NOT create the bridge.
- Keep the private gway-001 MCP bearer different from any client bearer.
- Store GWAY_MCP_BACKEND_BEARER in /etc/gway-mcp-gateway/backend.env with
  root owner and restricted group read for the gateway service.
- Keep credentials.sqlite3 owned by gway-mcp-auth:gway-mcp-read, mode 0640,
  and directory mode 0750. Gateway is a different user, with read only.
- Verify that the gateway cannot write DB or issue a bearer.

## Staging (explicit operator-approved Watchtower action)
    sudo sh deploy/mcp-bearer/stage.sh
    sudo -u gway-mcp-auth gway-remote bearer issue --days 30
    sudo -u gway-mcp-auth gway-remote bearer revoke KEY_ID

Use a secure interactive terminal. Never paste bearer secrets into GitHub,
ChatGPT, URL query parameters, logs or shell command arguments.

Only after backend transport and negative tests pass, authorize a local
systemctl start. Publish the Nginx example separately after TLS and
ChatGPT bearer compatibility are verified. The remote Mobile API and
WireGuard enrollment are not part of this change.

## Rollback
Stop the dedicated gway-mcp-gateway service. If a separate ingress activation
was approved, remove ONLY the new /mcp location, validate nginx -t and reload.
Leave Agent Ops and existing Watchtower services untouched. Preserve DB
for revocation/audit and follow approved secure backup retention.

IMPORTANT: private-plugin fixed bearer storage and real ChatGPT tool calls
remain separate acceptance tests; do not infer support from a manifest alone.

## Private bridge preparation
The staged gway-mcp-private-bridge.service binds ONLY Watchtower
127.0.0.1:19011 and transports to gway-001 127.0.0.1:8770 through a
host-key-pinned SSH session over WireGuard. The example ssh-config requires
a verified WireGuard address, a dedicated restricted SSH identity and a
pre-pinned known_hosts entry. The example 10.90.0.2 address must be
checked against current WireGuard state before enabling.
Do not reuse enrollment signing keys or the mobile API token.

Provision /etc/gway-mcp-gateway/ssh-config, bridge_identity, and known_hosts
with permissions allowing only the gway-mcp-bridge service identity to read
them. Deny SSH shell/remote commands for this identity at gway-001; permit
only the single local port forward via SSH server-side restrictions.
Separately start bridge and verify exact /mcp upstream, then start gateway.
The stage script deliberately starts neither unit.

## Readiness gates
- CI and local integration tests green.
- SSH target host identity pinned; bridge port forwarded only on loopback.
- Auth CLI issuer and verifier service users separated; verify group DB
  access 0640 without gateway DB write access.
- Backend MCP service active on gway-001 loopback with a separate secret.
- No public Nginx route until authorized, negative tests pass and actual
  private-plugin bearer support has been established.
