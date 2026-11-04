# M3 B2b-3 — Execution authorization and optional activation

**Default state: disabled.** Code deployment does not enable SSH execution or
advertise execution MCP tools. The existing seven read-only and three
inventory/preview MCP tools remain available with `gway:read`.

## Security boundaries

1. `gway:execute` bearer credentials are distinct from read-only credentials.
   An operator creates a scoped console proof once; the browser OAuth link derives
   access tokens only with the **same** scope and inherited expiry/revocation.
   The gateway checks `gway:execute` on every execution/result/cancel call.
2. No per-command Watchtower approval is necessary. Execution requires a valid
   execute-scoped connection, enabled gateway, current centrally granted
   eligibility, verified pinned identity and unique 32-hex request ID.
   Results and cancellation are owned by the stable parent proof identity
   across OAuth reconnects. Durable request claims prevent duplicate dispatch.
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

## One-time operator authorization and browser link

On the **Watchtower host**, issue a long-lived, revocable **execute-scoped**
operator proof with the canonical CLI in an **interactive terminal**:

```sh
sudo gway-remote bearer issue --scope gway:execute --days 30
```

For a read-only integration, the same CLI defaults to `gway:read`:

```sh
sudo gway-remote bearer issue --days 30
# Equivalent: sudo gway-remote bearer issue --scope gway:read --days 30
```

The CLI requires both stdin and stdout to be TTYs, switches from root to the
dedicated `gway-mcp-auth` account, and operates on the fixed private bearer
registry. Never pipe issuance to another process or capture it in CI, shell
logs, GitHub issues, agent transcripts, or ChatGPT. Save the issued bearer in
a protected secret manager; it is displayed only once. Revoke a bearer by its
public 24-character key ID, not by pasting its full secret:

```sh
sudo gway-remote bearer revoke <key-id>
```

The lower-level `scripts/mcp-bearer.py` remains a maintenance implementation,
not the recommended operator interface.

This is an intentional operator permission grant, not a per-command token.
Both the OAuth authorization-server metadata and MCP protected-resource metadata
advertise `gway:read` and `gway:execute`, while the authorization request
still defaults to `gway:read` if the client omits scope. To execute from ChatGPT,
the client **must request `gway:execute`** and the operator must link using an
execute-scoped proof; reconnecting an existing read-only proof does not elevate
its scope. Merely refreshing the plugin's tool schema does not change the
credential scope.
Protect the resulting secret and enter it only in the existing browser-link
page on `remote.arthexis.com`. The OAuth client must request
`gway:execute`. A read-only proof cannot authorize that scope.
OAuth browser-link behavior: when ChatGPT sends an explicit OAuth scope,
the form displays that exact requested permission and refuses any different
scope (even if the pasted bearer is valid). When the client omits scope, the
form defaults to **Read-only** and offers an explicit **Read and execute
commands** choice. Select the execute option **before submitting** an
execute-scoped bearer. The server checks the chosen scope against the token
and issues an access token with that scope only. It never silently upgrades
read-only authorization or accepts a read proof for execution. A rejected
`/connect` page now explains the scope requirement without revealing whether
a presented bearer is valid. On a failed or expired one-time form, initiate
a **new Connect** flow from ChatGPT; do not reuse the same page or create
another bearer unless the current proof is expired or revoked.

Current OAuth access tokens last at most one hour, and reconnecting creates
a fresh access credential derived from the same operator proof; it does not
require a Watchtower console action for each command. Expiration/revocation
of the parent invalidates all descendants. OAuth refresh tokens are not
implemented yet; reconnecting may still be needed when access expires.

Keep the operator bearer for future reconnections until it expires or
is revoked. Browser OAuth access credentials derived from it are short-lived;
a reconnect does not require running `bearer issue` again.

## ChatGPT OAuth scope negotiation

The MCP gateway advertises `gway:read` for read-only tools and
`gway:execute` for `node_exec`, `node_result`, and `node_cancel`
via each tool's `_meta.securitySchemes`. An execution call authenticated with
a read-only bearer returns HTTP 401 with an explicit
`WWW-Authenticate` challenge containing `scope="gway:execute"` and
`error="insufficient_scope"`. This requests a **new scoped OAuth consent
flow** from clients that support tool-level scope upgrades; it does not accept
the read-only bearer for execution or grant elevation itself.

The ChatGPT connection may still request `gway:read` for its initial discovery
session. That is valid; do not enter your `gway:execute` operator proof into
a browser form that explicitly requests `gway:read`, because this will fail
closed. Instead, invoke an execution tool and complete the execute-scoped
reauthorization prompt when offered. Use the already issued proof; do not
regenerate it unnecessarily. If ChatGPT does not start a scope-upgrade
challenge, the plugin's OAuth connection configuration must be updated in
the ChatGPT app builder; the server cannot change an explicitly requested
client scope. Check the `oauth_link` audit entries to confirm the scope
ChatGPT actually requested. Keep #333 open until the live ChatGPT invocation
passes.

Submit with `node_exec` using `node`, `command` and a fresh random
32-character lowercase hexadecimal `request_id`. No approval field is
accepted. Duplicate IDs cannot dispatch again, including after uncertain
delivery; use `node_result` to recover the original job. `node_cancel`
requires the same authenticated operator-proof identity.
The per-command operator `--approve` CLI has been removed.

Keep separate, root-controlled `sudo gway-remote exec grant <node>` and
`revoke <node>` commands. A granted node is not sufficient without a
scoped authenticated connection, pinned identity and gateway activation.

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

Test read-only OAuth, execute OAuth and cross-scope proof rejection; direct
execution of consecutive `hostname` and `uptime` without manual approval;
read-only bearer execution rejection; revoked proof and node eligibility;
wrong requester result/cancel denial; retry and concurrent duplicate IDs
(including altered commands), reconnect with the same operator proof,
identity rotation, uncertain-delivery no-redispatch, and bounded cancellation.
Verify unchanged OCPP and `gway-001`-only transport activation.

Deployment must not auto-grant nodes, change SSH relay privileges or silently
enable execution on new nodes. The operator-pinned execution config still
needs reconciliation after a host identity rotation.
