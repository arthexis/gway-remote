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

## Final review: SSH enforcement and protected secrets
Provision the bridge key only under
/etc/gway-mcp-gateway/bridge/id_ed25519 (0400 gway-mcp-bridge)
and pin the actual verified gway-001 SSH host key in
/etc/gway-mcp-gateway/bridge/known_hosts (0440 root:gway-mcp-bridge).
Directory: 0750 root:gway-mcp-bridge.
The dedicated remote SSH principal MUST NOT be the broad operator account
shown in the example. Replace User arthe after validating a dedicated
forward-only account on gway-001. The authorized key for that account must
have restrictions equivalent to:
    restrict,port-forwarding,permitopen="127.0.0.1:8770"
and the SSH daemon must explicitly disable PTY, agent forwarding, X11,
user rc and arbitrary shell/command access for that principal.
SSH authorized_keys permitopen restricts destination but cannot alone
restrict every local listening address; Watchtower's -L explicitly binds
127.0.0.1 and must be verified on the live host.

Do not stage if the installed /usr/local/bin/python3 cannot import
gway_remote.mcp_bearer_gateway. The staging script now checks this before
changing users or writing service files. It still does not create a bridge
key or an OAuth/MCP bearer.

Use root:gway-mcp-read 0640 for /etc/gway-mcp-gateway/backend.env
and verify that the gateway service user can read it, while other users
cannot. Only the separate administrator can mutate the credential
registry; the gateway account must not be able to write the database,
parent directory or SQLite sidecar files.

**Compatibility gate:** the example synchronous HTTP gateway is a
minimum read-only proxy, not yet proven compatible with every streamed
MCP response and session behavior. Keep public endpoint disabled until
a real client initialize/tools/list/tools/call exercise succeeds over
the exact deployed transport, including expected content types.
