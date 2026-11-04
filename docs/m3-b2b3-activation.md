# M3 B2b-3 — Execution authorization and optional activation

**Default state: disabled.** Code deployment does not enable SSH execution or
advertise execution MCP tools. The existing seven read-only and three
inventory/preview MCP tools remain available with `gway:read`.

## Security boundaries

1. `gway:execute` bearer credentials are distinct from read-only credentials.
   The verifier checks scope on every execution call. Existing OAuth/delegation
   routes cannot mint execute credentials: issue requires the explicit
   `operator_approved=True` flag in the trusted local registry interface,
   and execute delegation is disabled.
2. No API issues approvals. An operator with local access to the private
   Watchtower ledger issues a short-lived, single-use approval bound to the
   24-hex verified execute credential ID, gway-001, precise UTF-8 command,
   32-hex request ID, pinned SSH host public key fingerprint, and expiry.
   Approvals are consumed atomically. Result and cancellation require the
   same authenticated credential ID as the original request.
3. The fixed node protocol executes as `gway-exec`. A separate locked
   `gway-relay` SSH account is configured with ForceCommand, disabled
   password/keyboard login, no PTY or forwarding, and an exact sudoers command
   *only* to the protocol under `gway-exec`. Its authorized_keys is root-owned.
   Never give the Watchtower key access to an unrestricted interactive shell.
4. The Watchtower loader checks a fresh root-owned enrollment snapshot and
   the operator-pinned SSH key. It refuses unavailable/mismatched identity.
   The relay and node are hard-limited to gway-001 in this phase.

## Central execution eligibility (operator CLI)

Eligibility lives in the existing root-owned Watchtower enrollment SQLite database,
not in a hardcoded node allowlist or a separate inventory. All nodes start denied.
A grant is bound to the enrolled SSH host public key; enrollment revocation or
host-key rotation invalidates it. This command grants eligibility only—it does
not install a relay, activate the gateway, or create a command approval.

After deploying the corrected Watchtower runtime and verifying the enrolled
identity, perform the authorized initial grant:

```sh
sudo gway-remote exec grant gway-001
sudo gway-remote exec status gway-001
```

For immediate revocation of NEW jobs (running jobs are not silently cancelled):

```sh
sudo gway-remote exec revoke gway-001
```

Future grants use the same command with a different enrolled node; actual
execution transport is still limited to the currently provisioned pinned relay.
The command republishes the root-owned MCP inventory immediately. The gateway
rechecks grant, enrollment identity, address and reachability for each submission.
No read-only bearer can modify eligibility.

The ordinary Watchtower Ansible deployment installs the canonical `gway-remote` CLI launcher from the same immutable MCP runtime, and provisions
`/var/lib/gway-mcp-exec` as mode 0700 owned by the gateway service and installs
a systemd unit with only `ReadWritePaths=/var/lib/gway-mcp-exec`.
It does not issue execution credentials, create relay keys or set
`GWAY_MCP_EXEC_ENABLED=1`.

## Node preparation (separate, explicit operator action)

Provision a **new** ed25519 transport key pair using your approved secret
management process. Never commit or paste the private key into GitHub, an
issue or the MCP transcript. Provide only the public key to Ansible.

Set the following inventory overrides for `gway-001`:

```yaml
gway_exec_transport_prepare: true
gway_exec_relay_public_key: "ssh-ed25519 AAAA... dedicated-watchtower-relay"
```

Deploy through the existing Ansible workflow. Only gway-001 receives the
opt-in role. Before accepting a connection, verify `sshd -T -C
user=gway-relay,host=gway-001,addr=<watchtower-wireguard-address>` reports
the forced command, disabled forwarding, and public-key-only authentication.
Ensure a fake/invalid key and PTY/forwarding attempts are denied. Check that
the local OCPP services are unchanged. Do not run live power commands.

## Watchtower preparation (operator-controlled, not automatic)

Set up a *private* `/var/lib/gway-mcp-exec` directory owned by the gateway
service UID with mode 0700. The ledger is created as 0600.

Provision the separately managed identity private key and a pinned
`known_hosts` file, both readable only by the gateway service UID (0600).
Use the SHA256 hex digest of the decoded SSH host *public key blob* in the
root-owned `/etc/gway-mcp/execute.json`:

```json
{
  "enabled": true,
  "node": "gway-001",
  "address": "REPLACE_WITH_ENROLLED_WG_IPV4",
  "ssh_host_alias": "gway-001",
  "known_hosts": "/var/lib/gway-mcp-exec/known_hosts",
  "identity_file": "/var/lib/gway-mcp-exec/relay_identity",
  "host_key_sha256": "REPLACE_WITH_64_HEX_SHA256",
  "remote_user": "gway-relay"
}
```

This example is a **template**, not deployable configuration. Verify the
address and fingerprint against current enrollment. Ensure the root-owned
config file is not group/world-writable. The gateway must see a fresh,
identity-verified inventory snapshot with matching address.

Set `GWAY_MCP_EXEC_ENABLED=1` for the gateway **only after** you have verified
the restricted SSH identity and approved the field acceptance window. Merely
deploying this PR does *not* set this environment variable or create keys.

With the flag unset, `node_exec`, `node_result`, `node_cancel` are not
advertised and cannot run.

## Approval and use

For initial acceptance, issue a bounded execute bearer through the local
operator-managed credential registry; do not add scope issuance to the public
OAuth flows until authorization policy has been reviewed. Identify the
credential's 24-character key ID from the token's middle segment.

Issue the short-lived execute bearer **as the existing BearerRegistry database owner**, not necessarily the gateway service UID. On the field Watchtower the gateway UID cannot write the owner-controlled bearer database (`PermissionError`). Determine the owner of the actual configured registry database and use that trusted local account, without changing its ownership, chmod, group access or public OAuth scope. Substitute the real database path and owner in the following command:

```sh
sudo -u <bearer-registry-owner> /usr/bin/env PYTHONPATH=/opt/gway-mcp/current \
  /usr/bin/python3 -m gway_remote.watchtower_exec_service \
  --issue-execute-token --bearer-database /PATH/TO/EXISTING/BearerRegistry.sqlite3 \
  --lifetime 3600
```

Store the returned secret securely. The OAuth web consent flow deliberately cannot issue this token. Then run the local operator approval command:

```sh
PYTHONPATH=/opt/gway-mcp/current python3 -m gway_remote.watchtower_exec_service \
  --approve --principal <24-hex-key-id> --request-id <32-hex-request-id> \
  --node gway-001 --command 'uptime' --operator <operator-id> --ttl 90
```

The returned approval secret is valid only for those exact request fields.
Send it with an execute-scope call to `node_exec`. One-use means a retry of
the same approval fails; use `node_result` to inspect the already recorded
request, never mint an approval to replay an uncertain command. `node_cancel`
is limited to the original requester. No approval secret is logged or
included in result output.

## gway-001 user-manager field regression after deployment

The SSH forced command runs through the locked `gway-relay` identity and a narrowly
allowed sudo transition to `gway-exec`; neither SSH nor sudo necessarily provides
`XDG_RUNTIME_DIR` or `DBUS_SESSION_BUS_ADDRESS`. The node worker constructs them
from the effective `gway-exec` UID, checks ownership of the runtime directory
and user bus socket, and passes a minimal trusted environment to `systemd-run
--user`, `systemctl --user kill` and reconciliation. It never trusts SSH-supplied
bus variables. On failure the existing node job SQLite ledger retains a bounded
fixed-category `launch_diagnostic`, available through `node_result.stderr`;
raw subprocess stderr and secrets are never stored or returned.

After deploying the updated node package and preparing the restricted relay,
run the **explicit, opt-in on-node regression** as root on `gway-001`:

```sh
sudo /usr/bin/python3 scripts/test-node-exec-relay-field.py
```

This submits a fresh harmless `hostname` request via the *actual*
`gway-relay -> sudo -n -u gway-exec -> node_exec_protocol` command,
polls for its terminal result, and proves that user-systemd launches work
with the sparse forced-command/sudo environment. It does not invoke the
remote SSH handshake; separately retain the SSH host-key/forced-command
acceptance already recorded in #333. Test only after confirming no active
charging impact. Do not replay an uncertain request ID. The script must be
run from the deployed source checkout on the node.

## Acceptance

Test in order: read token forbidden from all write tools, execute token
without approval forbidden, tampered command/host/node denied, approval replay
denied, revoked execute token denied, wrong requester result/cancel denied,
identity change blocked, SSH disconnect `uncertain` never redispatched,
reconnect result retrieval, bounded cancellation, and unchanged OCPP.
Activate for **gway-001 only** after explicit operator signoff.

Limitations: the root-owned config is an operator-managed pin. It must be
reconciled to the live enrollment host identity whenever that changes.
This increment deliberately leaves public OAuth execute-scope issuance
disabled; the first field acceptance uses an explicitly operator-issued
execute bearer. Full OAuth consent UI/scope rollout can follow separately.
