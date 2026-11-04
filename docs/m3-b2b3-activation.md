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

As the private gateway service UID, issue a short-lived execute bearer via the existing private bearer registry (replace the database path with the gateway's actual configured `--database` path):

```sh
PYTHONPATH=/opt/gway-mcp/current python3 -m gway_remote.watchtower_exec_service \
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
