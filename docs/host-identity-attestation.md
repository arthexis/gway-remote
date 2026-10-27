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

## Current PR integration increment

The standalone bootstrap submits its existing ED25519 host public key in the
normal HTTPS enrollment POST; it refuses to invent/overwrite a host key.
Legacy clients may enroll without this field, but receive no SSH attestation.
The Watchtower enrollment transaction inserts a host identity with the reserved
device/operation/WireGuard identity and an opaque invitation binding. It advances
to active with the device and is removed on failed/rolled-back reservations.
The restricted schema-2 snapshot includes an optional `host_identity` record
for active nodes. Existing schema-2 consumers continue to receive their
original node/address/state fields.

**Not yet authorized:** acceptance of this record as an initial SSH pin,
automatic known-hosts writes, host rotation, or deployment. Those require the
trusted Watchtower authority verification and review of first-pin transition
semantics; the current controller continues to require independently pinned
host keys.

## Controller first-pin operation

`gway_remote.host_trust.pin_from_watchtower` obtains the current registry
through the separately verified, Bastion-backed Watchtower forced-command SSH
identity. The caller must explicitly approve the **initial** pin for an
approved node, and supply a dedicated existing 0600 `known_hosts` file.
The stable alias is `gway-inspection-<node>` and must be configured via
`HostKeyAlias` in the dedicated inspection SSH profile. The operation checks
snapshot freshness, active registry status, exact WireGuard enrollment binding,
host-key syntax, validity and revocation state; a changed key is never
overwritten. The function is not an automatic side effect of inspection.

## Remaining field and lifecycle gates

A full operator-approved key **rotation** procedure, pre-existing-device
retrofit policy, and Gway-004 end-to-end field acceptance are not completed
by adding first-pin support. No changes to production SSH profile,
`known_hosts`, WireGuard or enrollment state are implied by this PR.

## Explicit controller CLI

The only first-pin entrypoint is:

```sh
gway-remote inspection-host-pin --node gway-004 \
  --known-hosts /etc/gway-remote/inspection_known_hosts \
  --authorize-initial
```

The file must already exist, be owned by the operator executing the CLI, have
mode 0600 and reside under safe parent directories. The selected node must
be authorized by the deployed inspection inventory, and the remote snapshot
must be retrieved through the separately pinned restricted Watchtower SSH
identity. Omitting `--authorize-initial` is a verification-only check.
The command never edits `inspection-ssh.conf`; the approved SSH profile must
already set `HostKeyAlias gway-inspection-<node>` and reference the dedicated
known-hosts file. An identity mismatch fails closed; no rotation option is
offered by this command.
