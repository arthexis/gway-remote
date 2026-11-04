# M3 B2b-2: dormant Watchtower-to-node transport (PR under #333)

This increment adds **code only**, deliberately *not* an operational SSH
credential, authorized key, MCP tool or execution switch.

## Components

- `gway_remote.watchtower_exec_transport.RequestLedger` is a private SQLite
  one-shot journal. A request binds its 32-hex ID to the principal, exact UTF-8
  command, node, enrolled host-key SHA256 and expiry. A duplicate with any
  changed binding fails. `BEGIN IMMEDIATE` atomically claims a dispatch. A
  process crash or an SSH timeout after claiming leaves `dispatching` or
  `uncertain`: **never redispatch automatically**. Explicit result lookup
  can later reconcile with the local executor by that same request ID.
- `PinnedNode` is constructed from trusted Watchtower inventory, not an MCP
  argument. It validates the expected SSH host public key fingerprint against
  its root/operator-managed `known_hosts` file and a fixed WireGuard IP.
- `SSHTransport` invokes `ssh -F /dev/null -T` with strict host checking,
  private identity, forwarding disabled, no interactive shell, and a fixed
  protocol marker. The actual JSON command travels on stdin, never in SSH
  arguments. It rejects mismatched node/request response metadata.
- `node_exec_protocol.serve_one` accepts only a single bounded JSON message
  with `submit`, `result` or `cancel`. It verifies `gway-001`, rejects
  extra fields, uses `Jobs` under `gway-exec`, and never interprets
  `SSH_ORIGINAL_COMMAND`. Result output stays bounded by B2a.
- `DormantRelay` explicitly defaults to disabled. It is not connected to
  `mcp_bearer_gateway`, OAuth or an HTTP listener.

## Required before real dispatch

1. Provision a **separate** restricted SSH transport identity. The existing
   locked `gway-exec` account has `/usr/sbin/nologin`, so simply dropping an
   `authorized_keys command=` entry into its home cannot work. A safe
   arrangement needs an independently reviewed dedicated relay account/forced
   command, minimal privilege transition to the `gway-exec` worker, no
   arbitrary remote shell, no PTY/forwarding and no credential reuse.
   **This PR does not create such an account or change SSH/sudo policy.**
2. Tie the SSH host fingerprint and WireGuard endpoint to the root-owned
   enrollment ledger, verify current attestation, and provision Watchtower's
   private key and pinned `known_hosts`. Never take either from the caller.
3. Implement B2b-3: `gway:execute` OAuth scope, subject-bound one-use approvals,
   authorization on result/cancel, command/host/expiry binding and revocation.
   Only after that can the private `DormantRelay` be allowed to dispatch.
4. Add controlled end-to-end field tests and explicit activation approval.
   `execute_available` remains false; the legacy read-only tools stay intact.

## Durability and limits

The node keeps job IDs for seven days or until its 256-record capacity is
reached. The Watchtower ledger **never automatically forgets request IDs**;
it fails closed at 100,000 records. Operations beyond the node's retention
window must report unknown, not implicitly recreate an old command.
A future maintenance/archival policy must preserve replay tombstones.

No charging, network, sshd, systemd or Watchtower service is modified by this
increment. Fake SSH and private SQLite tests run in CI.
