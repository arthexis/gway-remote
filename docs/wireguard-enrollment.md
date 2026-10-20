# Gway Remote WireGuard enrollment — control-plane design

Status: **endpoint configuration implemented; enrollment server and bootstrap not implemented**.
Gway Remote owns this workflow. Agent Ops, Codex, GitHub Actions and the Android application are not enrollment prerequisites.

## Existing deployment and compatibility

- The existing Jelectric/Lightsail hub runs interface `gway` at `10.90.0.1/24`, UDP 51820.
- Existing `gway-001` is `10.90.0.2/32`; preserve keys, configuration and access.
- `scripts/register-wireguard-peer.sh` and `ansible/playbooks/adopt-wireguard-peer.yml` are a *manual, single-peer* adoption path and must not be reused as a multi-peer allocator.
- The operator-designated public origin is `https://register.jelectric.com`. Current ownership, HTTP routing, TLS termination, authentication and host filesystem deployment have **not** been verified. Do not replace that service blindly.

## Implemented in this change

```sh
gway-remote wireguard endpoint show
gway-remote wireguard endpoint set https://register.jelectric.com
```

The first command returns a built-in default if no local config exists. The second writes a mode-0600 local config atomically. Only the currently reviewed host is allowed, with a bare HTTPS origin and no credentials, path or query. These commands perform **no network request, public registration, key generation or changes to WireGuard**.

## Proposed next increment: host registration service

Install an independent, minimal enrollment service behind the existing HTTPS server on the hub. Keep management APIs on loopback or WireGuard only. The public endpoint only permits two unauthenticated operations: fetching a pinned, signed bootstrap manifest and redeeming a separately issued one-time invitation.

Operator-facing CLI (not yet implemented):

```sh
gway-remote wireguard status
gway-remote wireguard invite gway-004 --ttl 15m
gway-remote wireguard peers
gway-remote wireguard revoke gway-004
```

The operator authenticates to the *private* management service over an existing tunnel or SSH. The public registration host never issues invitations. The invitation is scoped to one node, short-lived, stored as a digest, single-use, rate-limited and revocable; do not put an enrollment token in a generic `curl | sh` URL, web server logs, shell history or the process argument list.

## Proposed device bootstrap

1. On a fresh Raspberry Pi OS Lite Trixie image, obtain the trusted bootstrap script from the fixed HTTPS origin; pin its signing key/hash or verify a signed manifest **before** execution.
2. Install only necessary packages (WireGuard tools; Ansible only if provisioning requires it). Use a local `root`-owned 0700 working directory.
3. Verify OS/hostname and refuse to overwrite an existing `gway` interface or conflicting `/etc/wireguard/gway.conf`.
4. Generate the private key on the new device, mode 0600. Send only the public key and an authenticated one-time registration proof to the server via HTTPS.
5. Under a serialized hub-side lock, allocate a unique unused /32 in `10.90.0.0/24`, reserve it persistently, and install the new peer with both file persistence and live `wg set` without restarting the existing interface. Reject duplicate hostnames/public keys/IP allocations and conflicting unmanaged peer blocks; preserve a backup.
6. Return the assigned /32, hub public key and endpoint. The device verifies identity, installs its configuration atomically, starts `wg-quick@gway`, and validates a new handshake. Do not route default internet traffic unless explicitly configured.
7. Record a durable receipt keyed by device identity, public-key fingerprint, allocated IP, creation/expiry and deployment outcome (not private keys or invitation secrets). Repeat submissions use stable, authenticated idempotency identifiers.

## Acceptance tests before activation

- Enroll gway-004 and gway-005 with distinct addresses and working handshakes.
- Existing gway-001 remains connected throughout; no restart and no configuration loss.
- Reused/revoked/expired tokens, duplicate public keys or node names, IP conflicts, hub errors and partial writes fail closed.
- Concurrent enrollment cannot allocate the same address; hub rollback is explicit on failed publication.
- Fresh-boot provisioning can run twice safely; existing unowned configurations are never silently adopted.
- Public API cannot list peers, issue invitations, reconfigure the hub or expose an authenticated management API.
- Full isolated test harness for Ansible plus a field report from Jelectric and a new Pi. CI alone is not field acceptance.

## Deployment order

1. Verify what currently serves `register.jelectric.com` (TLS, DNS, host owner, routes and backing services), without changing it.
2. Add a reviewed hub-side installer/service and contract tests.
3. Implement private control commands, invite/peer lifecycle, and a signed static bootstrap.
4. Implement client installer (Trixie) and integration fixtures.
5. Field-enroll one new box; only then enable repeatable bootstrap invitations.

**No existing endpoint or WireGuard configuration is changed by this PR.**
