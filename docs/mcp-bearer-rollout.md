# M2.1 private deployment runbook

The Watchtower gate remains separate from main deployment. The stage script
creates restricted Linux users/groups and directories and installs an inert
systemd unit. It does not start/enable the service or modify Nginx.

## Preconditions
- Confirm `/usr/bin/python3` is available. The dedicated MCP runtime is staged
  from an exact reviewed Git SHA under `/opt/gway-mcp/releases/SHA`, independently
  of the installed global zipapp and site packages.
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
    sudo sh deploy/mcp-bearer/stage.sh EXACT_REVIEWED_COMMIT_SHA
    sudo -u gway-mcp-auth /usr/bin/python3 -I /opt/gway-mcp/current/run.py bearer issue --days 30
    sudo -u gway-mcp-auth /usr/bin/python3 -I /opt/gway-mcp/current/run.py bearer revoke KEY_ID

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

The stage script requires an exact 40-character reviewed commit SHA and exports
only committed package and deployment files. It tests imports with the actual
`/usr/bin/python3 -I` launcher before changing users or units. It does not need
pip, network downloads, `/usr/local/bin/python3`, global site packages or a
replacement global `gway-remote`. Service users cannot modify root-owned code.
The release contains `manifest.json` with its commit and per-file SHA256 values;
a modified existing release is rejected. No bridge key or OAuth/MCP bearer is
created by staging.

For a separately approved gway-001 backend runtime only (no users, units or
service actions), use:

    sudo /usr/bin/python3 -I scripts/stage-mcp-runtime.py --revision EXACT_REVIEWED_COMMIT_SHA
    /usr/bin/python3 -I /opt/gway-mcp/current/run.py --check

Point the dedicated backend unit at `/usr/bin/python3 -I
/opt/gway-mcp/current/run.py mcp_http` with its independent protected environment.
The staging helper supports `--prefix` for hermetic packaging validation. The
production units use the fixed `/opt/gway-mcp` prefix.

`current` selects the staged release for the next service start; an existing
process keeps running. `previous` retains the preceding selected release and
idempotent restaging does not overwrite it. Before changing a selection, record
the old link. A separately authorized rollback stops only the MCP services,
atomically replaces `current` with a link to the recorded prior release, and
starts only those services again. Staging itself never starts, enables or
restarts a service and never edits Nginx. Keep old releases for rollback.

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
