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
    sudo gway-remote bearer issue --days 30
    sudo gway-remote bearer revoke KEY_ID

Run these commands on Watchtower. The CLI drops root's supplementary groups,
primary group and user identity to the fixed `gway-mcp-auth` service account
before opening the registry. It never creates a missing account or changes
registry ownership. Running directly as that auth owner remains supported;
other unprivileged users receive guidance to use sudo. Issuance requires both
stdin and stdout to be interactive terminals, including when invoked with sudo.

For an older Watchtower global CLI that lacks `bearer`, install the reviewed
CLI from a clean, pinned checkout using `sh scripts/install-cli.sh`. Back up
`/usr/local/bin/gway-remote` first and restore that file to roll back. This
standalone installer replaces only the global zipapp; it does not restart
services, modify OAuth configuration, change the isolated MCP runtime pointer,
or issue a token. Do not use the general backend deployment merely to install
this console command.

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

## Ongoing updates via canonical Ansible deployment

**After initial private OAuth provisioning**, an already enabled Watchtower
`gway-mcp-link.service` with protected
`/etc/gway-mcp-gateway/link.env` and an existing
`/opt/gway-mcp/current` release is managed automatically by the normal:

```sh
git pull --ff-only
./deploy.sh
```

The regular wrapper invokes `ansible/playbooks/watchtower-mcp.yml`
**before** the same-revision shortcut. Ansible stages the precise Git SHA
into the existing root-owned isolated MCP runtime, validates Python imports,
updates the OAuth unit only when different, and restarts only
`gway-mcp-link.service` when the SHA or unit changes (or the enabled service
is stopped). The loopback OAuth discovery metadata must return a 200 with
the expected issuer, PKCE and RFC 9207 support. On failure it restores the
previous selected runtime and the original OAuth unit, restarts the dedicated
link service, and exits with an error.

The existing CLI/API Ansible deployment still runs unchanged. This does **not**
install MCP on unprovisioned hosts, publish Nginx, restart gateway/bridge,
touch WireGuard, or issue credentials. The currently installed
`gway-mcp-link.service` must already be enabled; no first-time activation is
inferred. For emergency isolation, run `GWAY_REMOTE_SKIP_MCP=1 ./deploy.sh`
to retain the ordinary GWay Remote deployment without touching MCP.

First-time MCP setup and public ingress changes remain separate explicit
operator authorizations. Do not use `stage.sh` as a routine update mechanism
after this migration.

## ChatGPT action discovery compatibility

The OAuth callback and token exchange can succeed even when ChatGPT's next
MCP discovery request fails. Modern clients may send the stateless
`server/discover` protocol probe using revision `2026-07-28` rather than
the older `initialize` + `tools/list` sequence (`2025-03-26`).

The **Watchtower gateway** now handles an authenticated modern
`server/discover` response and translates modern read-only `tools/list` /
`tools/call` messages into the existing legacy private backend protocol.
It adds the modern required `resultType: complete` to successful results.
The seven fixed read-only tools and the existing OAuth bearer enforcement are
unchanged. An unauthenticated discovery remains HTTP 401; `agent_submit`
and arbitrary RPC methods remain denied. This gateway adaptation allows
Watchtower to accept modern ChatGPT discovery **without requiring an immediate
update of gway-001's deployed MCP backend**.

The canonical Watchtower Ansible deployment now restarts and checks the
previously enabled, dedicated `gway-mcp-gateway.service` when the isolated
runtime changes, alongside the existing OAuth link; failed activation
restores the previous release pointer and restarts those dedicated units.
It does not alter Nginx, WireGuard, the bridge, OCPP, or service credentials.

After merging, deploy the same branch on Watchtower using
`git pull --ff-only && ./deploy.sh`, then reconnect ChatGPT and verify its
seven discovered tools. Do not issue/revoke any bearer merely to debug
MCP tool discovery. Record sanitized HTTP status/protocol version and tool
count, never authorization headers, credentials, codes or URL queries.

## M3 increment A — one enrollment registry, two read-only consumers

Watchtower's existing protected enrollment SQLite ledger
(`/var/lib/gway-remote/watchtower/ledger.sqlite3`) remains the **only source
of registered node identity**. No manually edited node names, IP inventory, or
independent MCP registry are introduced.

The deployed Watchtower Ansible playbook installs a root-only snapshot publisher
(`gway-mcp-inventory-refresh.service`) and a periodic timer (45 seconds).
It exports only active enrolled nodes into a short-lived root-owned
`/var/lib/gway-mcp-auth/node-inventory.json` (0640 root:gway-mcp-read).
The snapshot expires after 120 seconds; missing/stale/untrusted data fails
closed. The gateway has no direct access to the root-owned enrollment database.

The parent `/var/lib/gway-mcp-auth` is mode `0750` and contains credential
registry material. Normal operator accounts **must not** be added to
`gway-mcp-read` just to run Ansible inventory. The Watchtower Ansible
playbook verifies the exporter with task-local `become: true`, and
interactive `ansible-inventory` commands use `sudo` for this protected view.
No file or directory mode is relaxed by this fix.

Two independent read-only views consume this **same derived snapshot**:

```sh
# Watchtower: Ansible dynamic inventory. Does not authorize deployment.
# Run discovery with sudo because snapshot resides under the protected
# MCP authentication directory. Do not add the operator to gway-mcp-read.
sudo ansible-inventory -i /usr/local/sbin/gway-enrolled-inventory --list

# Combine enrolled identities with existing declarative management policy:
sudo ansible-inventory -i ansible/inventory/deployment.yml \
  -i /usr/local/sbin/gway-enrolled-inventory --list
```

The same connected ChatGPT plugin exposes `node_list` and
`node_capabilities(node)`; no new OAuth client or MCP connection is needed.
Only node names, identity-verification state, and explicitly **unknown**
reachability appear in MCP. Raw WireGuard addresses, SSH host public keys and
registration evidence are not returned through those tools.

The existing `ansible/inventory/deployment.yml` is still the source of
**desired management policy**, not registered-node existence. The generated
Ansible host group `gway_enrolled` does **not** set `ansible_host`,
`ansible_user`, deployable repository lists, command permissions, or default
SSH access. An entry in the old static policy but absent from the Watchtower
ledger is **not** considered enrolled. Older manually established peers may
need an explicit identity adoption before they appear, rather than being
silently trusted.

This increment adds no command runner, new roles or public routes, grants
no execution scope, and does not probe/SSH nodes. A later increment can add
independently observed health and a separate explicit execution authority.


## M3B prerequisite — adopt an already-configured WireGuard peer

`watchtower adopt` adds an existing **operator-approved** WireGuard peer to the
authoritative Watchtower enrollment ledger, without bootstrap URLs, key rotation,
address allocation, editing `wg-quick` configuration, calling `wg set`, changing
SSH trust, or enabling command execution. It does **not** prove SSH host identity;
the MCP projection must report `identity_verified=false` until separately attested.

Before adoption, independently confirm the node's WireGuard public key with the
node operator over a trusted administrative channel. The exact key is mandatory:
hostname, peer IP, and WireGuard connectivity alone are insufficient to authorize
registration. Verify the existing peer is in both Watchtower's persistent
WireGuard config and its live `wg show gway allowed-ips` output, with the same
single private management /32 in the configured network. A mismatched key,
address, duplicate peer, revoked record, or existing different node identity
must fail closed.

Run on Watchtower as root, substituting the **existing** enrollment service's
ledger, network, gateway, and WireGuard configuration values:

```sh
sudo gway-remote watchtower adopt gway-001 \
  --ledger /var/lib/gway-remote/watchtower/ledger.sqlite3 \
  --network <WATCHTOWER_NETWORK_CIDR> --gateway <WATCHTOWER_GATEWAY_IP> \
  --config <EXISTING_WIREGUARD_CONFIG> \
  --public-key '<INDEPENDENTLY_VERIFIED_NODE_WG_PUBLIC_KEY>' --dry-run

# Remove --dry-run only after reviewing the identity/address.
sudo gway-remote watchtower adopt gway-001 \
  --ledger /var/lib/gway-remote/watchtower/ledger.sqlite3 \
  --network <WATCHTOWER_NETWORK_CIDR> --gateway <WATCHTOWER_GATEWAY_IP> \
  --config <EXISTING_WIREGUARD_CONFIG> \
  --public-key '<INDEPENDENTLY_VERIFIED_NODE_WG_PUBLIC_KEY>'

sudo systemctl start gway-mcp-inventory-refresh.service
sudo ansible-inventory -i /usr/local/sbin/gway-enrolled-inventory --list
```

Dry-run opens the ledger read-only and never writes. Adoption inserts one
`active` device and a committed `adopt` audit operation atomically;
an identical existing registration is a no-op. The periodic inventory
publisher otherwise discovers the change on its next refresh. No host identity
attestation row is fabricated and no executor role is granted.
