# gway-002 Watchtower SSH pin: journalled operator-only transaction (#614)

**Code-only; NO field activation.** This implements Stage B of the existing
`docs/gway002-relay-acceptance.md` (Draft Remote #630), not the node-side
forced-command relay, WireGuard enrollment, AgentOps installation or a new
authentication service.

## Current prerequisite

Previous field evidence: 002 is actively WireGuard enrolled, attested and
reachable, but its restricted Watchtower relay SSH authentication failed
(`ssh_auth`, exit 255). A verified gway-002 SSH **host** public key already
exists at `/etc/gway-remote/verified-gway-002-host.pub`. Do not create or
rotate host keys. Before any apply, the operator must separately provision
and accept the **client** relay public key on 002 via an independently
authenticated administrative path, and demonstrate the strict SSH
`limits` protocol works. The command below has **no network access**;
`--relay-confirmed` is an operator attestation, not automatic proof.

## Read-only plan (Watchtower root operator)

```sh
sudo python3 -m gway_remote.watchtower_pin_002 preview \
  --service-uid <verified-live-gateway-service-UID>
```

Reads only the existing root-owned `/etc/gway-mcp/execute.json`,
the exact private known_hosts and identity-file metadata referenced there,
the existing already verified 002 host key and the authoritative **read-only**
enrollment ledger plus fresh root-published inventory. Requires:
- Existing enabled **multi-node** config with unique pinned nodes (001/004).
- One shared existing private known_hosts and SSH identity, safe owner and
  0600 mode; owner must be the independently verified gateway service UID,
  which may differ from root. This command does **not** read the private
  identity's content or change its owner.
- Existing host pins match exactly their configured SHA-256 of decoded SSH
  public-key blobs (not hashes of text files).
- 002 host public key matches active, non-expired **ledger** attestation
  and the root-protected verified public-key file; fresh eligibility,
  reachability and exact enrolled WireGuard /32 address agree.
- No existing 002 pin or duplicate aliases. Nothing discovered over SSH.
- Planned config within the installed 4096-byte limit.

Output contains only a status, no private addresses, keys, source contents
or credentials. A failed preflight does not create a journal or change files.

## Explicit apply — requires separate change authorization

```sh
sudo python3 -m gway_remote.watchtower_pin_002 apply \
  --service-uid <verified-live-gateway-service-UID> \
  --relay-confirmed \
  --approval I_ACCEPT_GWAY_002_WATCHTOWER_PIN
```

This is **not approved merely by merge**. It requires a reviewed maintenance
window, fresh node-side relay acceptance, a stable gateway/service identity,
and agreement on a recovery plan. Do not run until these are evidenced.

On apply, a one-shot, root-private state directory
`/var/lib/gway-remote/watchtower-pin-002` is created exclusively.
The module fsyncs exact **before and after** images of both files plus
a journal; preserves root and gateway-service UID/GID/modes; verifies
compare-and-swap preconditions; atomically replaces the service private
known_hosts first, then root `execute.json`, fsyncing each directory.
Existing node entries and known_hosts lines are retained verbatim except
the appended 002 entry. **It does not reload/restart Watchtower services.**

**Important POSIX limitation:** two independent path replacements are
not simultaneously atomic. A crash can leave a mixed file generation.
A durable journal plus separate `recover` action makes this situation
detectable and recoverable, not invisible. Watchtower must **not** reload
or dispatch to 002 during the pending/mixed state. Any unexpected external
writer must be stopped; this tool does not lock arbitrary system
administrators or a live gateway. Before an apply, validate that no other
configuration convergence is running.

After both readbacks, the persistent state remains
`pending_acceptance`. No automatic promotion, SSH probe, AgentOps activation
or deletion of backups occurs. Acceptance requires independent runtime
checks and an operator decision.

## Explicit recovery

```sh
sudo python3 -m gway_remote.watchtower_pin_002 recover \
  --approval I_ACCEPT_GWAY_002_PIN_ROLLBACK
```

Recovery validates the root-private journal, exact backup/staged hashes,
target paths, UID/GID, modes and current file bytes. It **refuses** unknown
concurrent changes; no unverified overwrite or `ssh-keyscan`. It restores
`execute.json` first (removing 002 from the routing config), then private
known_hosts, with per-file atomic replacement and fsync. Rerunning recovery
after successful rollback reports `already_rolled_back`. Retain the
journal/backups until reviewed archival: later apply attempts fail closed
while the directory exists. If the process dies during initial preparation
before a complete journal exists, stop and inspect the protected incomplete
transaction manually; never automatically delete it.

## Runtime acceptance outside this PR

1. Confirm independent gway-002 admin route and receiver forced command
   under Draft #630, no copy of any 001 private key.
2. Confirm strict SSH from Watchtower to 002 with *the already trusted*
   002 host key and accepted client relay public key; capture sanitized
   `limits` receipt. This command is not issued by the pin module.
3. Check any pending journal before Gateway reload. Verify the actual
   service UID, config metadata and pinned key as that **service** account;
   call installed `watchtower_exec_service.load_service` through the
   approved operator path and verify node doctor appropriately.
4. Only then authorize a minimal Gateway reload and bounded
   `node_exec`/`node_result` acceptance with fresh request ID.
5. Keep AgentOps #101 in Draft until local Codex, GitHub, owner identity,
   workspace and restricted federation scopes on 002 are independently
   verified. No scheduler activation.

At every stage `gway-002` stays `production`, inventory
`remote_managed_repositories: []`, and no general Appliance Deploy grant
is introduced. CI uses disposable filesystem fixtures; CI success does
not prove current field state.
