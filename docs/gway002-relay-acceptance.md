# gway-002 restricted SSH relay — staged operator acceptance (#614)

**Current state (2026-11-18): NOT ACCEPTED.** Watchtower already identifies
gway-002 as enrolled, attested and reachable. The read-only #614 evidence
establishes both `execute.json`/known_hosts missing 002, and a strict SSH
authentication failure (`ssh_auth`, exit 255) against 002. The latter is
independent of Watchtower's missing persistent pin.

## Trust separation and administrative access

**Two different public keys must not be confused:**

1. **Watchtower relay-client public key**: operator-approved public counterpart
   of Watchtower's existing private SSH relay identity. It will be authorized
   for the *restricted* `gway-relay` login on gway-002. This PR never copies
   the private key or uses the 001 identity as a substitute.
2. **gway-002 SSH host public key**: root-protected, already attested at
   `/etc/gway-remote/verified-gway-002-host.pub` on Watchtower. Only this
   key may populate Watchtower's gway-002 `known_hosts` entry.

Existing gway-001 Bastion access to Watchtower proves **Watchtower access**,
not an administrative SSH route to 002. The previous strict probe against
002 failed `ssh_auth`. No independently authenticated 002 administrative
route is presently evidenced. Use an operator-confirmed local console or
another existing pinned administrative route; **do not** use the rejected MCP
executor to bootstrap its own SSH permissions. Do not add public SSH, TOFU,
`ssh-keyscan` as trust, or `StrictHostKeyChecking=no`.

## Stage A: gway-002 local preflight and narrowly scoped relay provision

From an exact, reviewed gway-remote checkout **on 002 as arthe**, after
establishing an independent administrative session, stage *only the reviewed
Watchtower relay public key* at the fixed root-owned path
`/etc/gway-remote/approved-watchtower-relay.pub`, as a non-symlink regular
file under a protected root-owned directory. Verify
its SHA-256 digest out of band against the Watchtower origin; pass the digest
only. The fixed staging path cannot be overridden with another arbitrary path. Independently verify the installed executor
identity (`gway-exec` or `arthe`) and use the observed value as the expected
value: the playbook **never changes it**.

```sh
ansible-playbook -i localhost, -c local \
  ansible/playbooks/gway002-relay-only.yml \
  -e '{"gway_002_expected_executor_user":"<verified-existing-user>","gway_002_relay_public_key_sha256":"<sha256-of-that-file>"}'
```

Default mode is preflight/read-only. It verifies the **actual local hostname**,
invoking user, root-managed executor identity, installed receiver module,
public-key file and digest, and existing relay file safety.

**Not authorized by this PR:** a future operator may repeat with JSON-typed
`"gway_002_relay_apply":true` and
`"gway_002_relay_approval":"I_ACCEPT_GWAY_002_RELAY_ONLY"`.
Only then does the playbook include the existing
`ansible/roles/gway_remote/tasks/node-exec-relay.yml` recipe (restricted
gway-relay account, one approved public key, forced protocol, validated
sshd/sudoers). It does **not** invoke the general role, modify WireGuard or
change `remote_managed_repositories`.

The playbook snapshots pre-existing relay-file bytes in its **runtime** and
attempts to restore them on handled failures. This is **not a durable,
power-loss-safe rollback guarantee**: before any production apply, the
operator must record a separate protected durable backup and prove
independent administrative access and a recovery procedure. A missing SSH
principal/receiver, active SSH conflict, unsupported sudo policy or uncertain
backup blocks application; no retries by guessing. Any unmatched existing
relay configuration requires explicit review before apply.

## Stage B: Watchtower SSH pin after authenticated node protocol

Only after the node-side public-key/forced-command receiver is present and a
**separately authorized** strict SSH `limits` read proves it accepts the
existing Watchtower relay identity:

1. Read the existing current authoritative 002 WireGuard address and confirmed
   attestation from Watchtower's published enrollment inventory. Independently
   validate the root-owned already-verified 002 SSH host **public** key with
   `watchtower attest gway-002 --dry-run`. Do not rotate, replace or generate
   either key.
2. Preserve the exact existing `/etc/gway-mcp/execute.json` and the
   **service-owned** private `known_hosts` as durable backups. `PinnedNode`
   requires the known_hosts and private identity-file owners to match the
   **gateway service EUID**; do not `chown` either to root to satisfy a root
   diagnostic. Check no gway-002 alias already exists.
3. Add precisely one `gway-002 ssh-ed25519 <verified-host-public-key>` entry
   to that private known_hosts, preserving existing 001/004 aliases and owner,
   group and 0600 mode. The pinned `host_key_sha256` is the lowercase hex
   SHA-256 of the decoded SSH public-key blob, **not** the SHA of its text file.
4. Extend the existing root-owned multi-node `execute.json` with an exact
   `gway-002` node entry: its current enrolled private address, alias
   `gway-002`, verified host-key digest, existing approved Watchtower relay
   identity path, private known_hosts path, and restricted user `gway-relay`.
   Preserve all current entries. Validate with installed
   `watchtower_exec_service.load_service()` under the gateway's service
   identity. Stage and atomically publish both files as one reviewed
   maintenance operation with explicit rollback; avoid an interval in which
   the gateway sees inconsistent config. Revalidate before/after reload.
5. Validate `node doctor` with correct identity, then one authorized
   `node_exec` / `node_result` pair using a fresh request ID. Never replay
   an uncertain request. Restore exact previous files and service state if
   the pinned transport fails.

Stage B is currently **operator procedure only**, not an automated apply
recipe: current source exposes validation, not an accepted transactional
two-file Watchtower pin installer. A separate reviewed implementation and
specific authorization are required before doing those writes.

## AgentOps remains a separate authorization boundary

A functioning `gway-exec` receiver does **not** mean AgentOps can read
`/home/arthe/.local/share/gway-agent-ops`. Before applying AgentOps PR #101,
verify the actual node-local provider process identity, private workspace,
Codex/GitHub authentication **on 002**, release SHA and executable permissions.
If the receiver is still `gway-exec`, do not silently migrate it to
`arthe` and do not relax private-home permissions: obtain a separate reviewed
handoff or identity change authorization.

Keep 002 classified `production`, with
`remote_managed_repositories: []` denying generic deployment writes.
Do not enable AgentOps provider, scheduler, recurring tasks, or a real Codex
execution until an independent acceptance gate is approved.
