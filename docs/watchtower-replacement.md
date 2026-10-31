# Watchtower replacement protocol (issue #301)

This is the server half of `gway-replace-v1`. The standalone client implementation
and local recovery/console acceptance belong to #302. A server PR or green CI
does not authorize installation, a live replacement, a new bearer, or SSH access.
Keep #301 open until both implementations, explicit rollout approval, and the
dual-sided field receipt are complete. The current downloaded client rejects the
new flags; it must not be worked around by running the ordinary bootstrap path.

## Authorization and transport

Only a private `register NODE --replace` session with an unused, unexpired,
unrevoked invitation and `replace_authorized=1`, purpose `enroll`, can prepare a
replacement. The session device and invitation device must agree. The URL query
must be exactly `replace=true`, including the downloaded `client.py` URL and
replacement POSTs. Duplicate flags, encoded alternatives, repair flags, extra
fields, duplicate JSON members, and ordinary or repair invitations fail closed.
Legacy `/v1/enroll` and `/complete` reject replacement invitations.

The generated root bootstrap retains the Watchtower and exact hostname gates. It
downloads the standalone client and invokes `bootstrap --replace
--replacement-protocol gway-replace-v1` with the existing device, server-key and
protected token-file arguments. The replacement client owns acknowledgment; the
shell never runs legacy completion. An older client fails argument validation.

Use HTTPS JSON POSTs to `/v1/bootstrap/<session>/replacement/ACTION?replace=true`.
The server binds the secret to its invitation, device and one operation. All
responses and artifacts use `Cache-Control: no-store`; request logging is disabled
and error responses contain only generic fixed strings. Never log the URL or
place it, peer keys, configuration, or private addresses in an issue receipt.

| Action | JSON fields in addition to `protocol`, `device`, `public_key` |
| --- | --- |
| `prepare` | Optional `ssh_host_key`, required to match an existing active attestation |
| `ack` | `operation_id`, `activated: true` |
| `status` | `operation_id` |
| `rollback` | `operation_id` |

`protocol` is exactly `gway-replace-v1`. Preparation returns the operation ID,
candidate `address`, approved `server_endpoint`, `server_public_key`,
`server_tunnel_ip`, `activation_after`, `expires_at`, `rekey`, and durable `state`.
The satellite must bind all responses to its session, operation, device, key,
approved Watchtower identity and protocol. It must persist the operation ID and
local backup before changing its interface. A retry of the identical preparation
returns the same reservation; a changed key or device is rejected.

## Peer and SSH identity semantics

For a rekey, allocate a different free /32 inside the existing hub network. Add
one temporary, exactly marked managed candidate peer; retain the original peer,
address, persistent stanza, active device row and SSH binding. Allocation includes
all configured peers, active devices and pending replacement reservations. A
full config/runtime inventory must agree before reservation. Duplicate keys,
overlapping address ownership, ambiguous markers, an unmanaged source peer, or
unrelated runtime/config drift block changes.

The satellite stages its root-only original and candidate files, switches only
after `prepared`, verifies its own active interface and approved hub handshake,
and sends `ack` only after successful activation. The server independently
requires the candidate peer's exact AllowedIPs and a WireGuard handshake strictly
after `activation_after`, no older than 180 seconds and not in the future. The
client may need to wait for the next handshake; a stale handshake cannot commit.

An unchanged WireGuard key is a validation transaction: preserve its existing
/32, configuration and runtime peer. It still requires a fresh handshake and
acknowledgment, and it never deletes/readds the peer. `old_peer_retired=false` is
expected for this mode.

An existing SSH attestation must be active, unexpired, bound to the old WireGuard
identity, and match the supplied host key exactly. Replacement preserves that
host key, its original dates and expiry; commit changes only its operation and
WireGuard enrollment binding. The immutable replacement row retains the previous
binding. Revoked/stale bindings and key substitution block replacement. If no
attestation exists, omit `ssh_host_key`; replacement preserves its absence. Initial
SSH trust or repair remains a separately authorized task. No SSH file is changed.

## Durability, restart and rollback

The `replacements` SQLite table stores the immutable previous device and SSH
records, candidate identity/address, authorization hash, original configuration
digest, backup path, handshake boundary and state. It stores no bearer or private
key. The configuration backup contains private material and is restricted to
the service UID with mode 0600 in the existing private backup directory. Atomic
backup creation and configuration replacement fsync their files and directories.
The original backup is never overwritten or silently recreated from a changed
configuration. All mutating paths use the existing thread lock and file lock.

| Durable state | Restart/retry behavior |
| --- | --- |
| `reserved` | Verify/create the original backup, add only the candidate stanza and runtime peer; never retire the old peer |
| `prepared` | Retain both peers and the old active node; wait for authenticated verified activation |
| `acknowledged` | Finish the accepted commit, including after a restart crosses invitation expiry |
| `rolling_back` | Restore only the old owned stanza/peer and remove only the owned candidate |
| `committed` | Return the exact receipt on bound ack/status retries; never reapply |
| `rolled_back` | Return the bound rollback/status receipt; never reprepare with this session |

After durable acknowledgment, commit changes the owned persistent stanza,
retires the old runtime peer only for rekeys, verifies runtime/config agreement,
then atomically publishes the new active node/attestation and consumes the session
and invitation. A restart after file write, runtime apply, peer retirement or
before SQLite commit continues the recorded intent. The old and new peers never
share a /32. The old kernel route remains available until acknowledgment; the new
address uses the existing hub network route. No route, firewall, default route,
other node, or OCPP service is changed.

Before acknowledgment, an expired/revoked session rolls back on the next startup,
authorized mutating operation or private `watchtower recover`. Pending allocations
remain reserved until recovery proves the candidate removed. There is no new
background cleanup service. A durable accepted acknowledgment is a commit
decision: private revocation returns false during that phase; recovery completes
it even across expiry. Explicit authenticated rollback can still resume an
incomplete operation before commit. Terminal ack/status/rollback retries require
the same session, operation, device and key and remain available only until expiry;
new preparations and artifact downloads reject consumed sessions.

Rollback preserves unrelated configuration bytes, including later operator
comments and other nodes' newly enrolled peers. It does not restore the full
snapshot over concurrent work. If an owned key/address/block, backup or unrelated
runtime ownership changed unexpectedly, stop with the durable operation retained
for operator review rather than deleting peers or guessing. On a client crash or
missing commit response, #302 must consult `status`, retain the local backup, and
restore the old local tunnel only after an acknowledged server rollback. After
session expiry use the approved local console and private server recovery; never
weaken SSH verification or reuse a leaked URL.

## Field gate and sanitized receipt

Do not deploy or issue another replacement session until the server/client PRs,
matching downloaded-client tests, CI, recovery proof and explicit rollout
approval are recorded on #301/#302. At that gate, capture private server ledger,
config/runtime and handshake evidence and a protected backup; independently
confirm console recovery access on gway-005. Deploy only the approved enrollment
runtime, validate exact installed revision and authorized/forged bootstrap
behavior, then privately issue a fresh short-lived session. The exposed session
was revoked under #301; never restore it from the administrative backup.

Validate server prepare/ack/commit or rollback receipts and absence of unrelated
peer, route, public edge and OCPP changes. The client issue additionally owns
reboot persistence, physical/local activation and SSH continuity. Report only
sanitized states/booleans: `prepared`, `committed`, `replaced`, `old_peer_retired`,
`new_peer_active`, `handshake_fresh`, `ssh_identity_preserved`, `rollback_tested`,
`reboot_persistent`, `unrelated_peers_unchanged`, `routes_unchanged`,
`ocpp_services_unchanged`; distinguish server observations from node attestations.
