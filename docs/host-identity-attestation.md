# Issue #280: SSH host attestation security contract

Status: **first implementation increment only; NOT ready for deployment or auto-pinning**.

The `host_identity` module validates one Watchtower-authenticated SSH ED25519
host identity assertion, its enrollment binding, tunnel public identity and
revocation/rotation status. It deliberately **cannot** accept a missing existing
pin or rotate a mismatched pin. It never contacts the device or changes
`known_hosts`. Authentication of the registry snapshot by strict, Bastion-backed
Watchtower SSH remains mandatory. A JSON record by itself is not a credential.

## Remaining integration requirements

1. Audit the actual existing enrollment service and bootstrap client paths; add
   host public-key handoff bound to the redeemed single-use invitation and the
   accepted WireGuard public key. Preserve existing `sshd` identities and fail
   on conflicting configuration. Never upload SSH private keys.
2. Extend the durable enrollment ledger transaction with an immutable host-key
   identity record and explicit revocation and operator-approved rotation
   transitions. Reject retries that attempt to change either identity.
3. Extend the restricted, read-only Watchtower exporter; choose an authenticated
   schema evolution compatible with existing schema-2 inspection consumers.
   A fresh export must prove current server-side authorization/revocation status.
4. Authorize a **first pin** only with a verified enrollment transaction linked
   to the Watchtower trusted authority and approved node. Pin in a dedicated
   protected known-hosts file, stable HostKeyAlias, and reject unexpected changes.
   Keep BatchMode and StrictHostKeyChecking enabled. Never use ssh-keyscan as
   independent proof of identity.
5. Test replay, revoked invite, mismatched WG key, host substitution, inactive
   node, corrupted ledger, stale snapshot, hostile symlinks, crash recovery,
   unauthorized key rotation and rollback with separate isolated environments.

Do not deploy, restart SSH/WireGuard, add remote access, or treat enrollment as
authorization to inspect/deploy. Field acceptance remains in #274 and #258.
