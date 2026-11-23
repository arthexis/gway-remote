# PR #699 / Issue #682 — SD injector, deferred Watchtower claim and RPi Connect

**Status: Draft, hermetic canary only. No production changes have been applied.**

## Design

1. Windows Raspberry Pi Imager writes a stock, fresh Pi OS image and its
   own user/hostname/network/SSH/Raspberry Pi Connect auth-key configuration.
2. gway-001 generates a **new Ed25519 private key per card** and emits only
   its URL-safe public key. The private key is held in a root/operator-protected
   local file, never in an argument, receipt, log, or Watchtower.
3. An authenticated root operator at Watchtower calls `prepare` on its
   **existing enrollment SQLite ledger**. Watchtower stores the public key and
   a revocable preparation ID, initially valid for 24h (maximum 48h).
4. gway-001's SD injector mounts only the FAT bootfs of a *removable* card,
   validates disk/mount identity, and structurally updates existing Imager
   `user-data` (it does not flash/format/partition). It includes the private
   installation key, claimed preparation ID and two first-boot components:
   **Raspberry Pi Connect user-manager repair**, and a **persistent systemd
   deferred enrollment service**. All original network, SSH, users and runcmd
   entries remain intact.
5. After a fresh boot, the installation service obtains a 2-minute challenge
   over pinned-host HTTPS, signs domain-separated bytes using the card key,
   then receives a **new two-hour** scoped bootstrap session from Watchtower.
   The first claim and invitation/session creation are a single
   `BEGIN IMMEDIATE` SQLite transaction. Signed retry uses a fresh challenge
   to obtain the **same** Fernet-sealed session without resetting its lifetime.
6. Existing bootstrap then installs/configures WireGuard and the requested
   installer identity. The Connect service is activated separately using
   `loginctl enable-linger` and the Imager sign-in path. **No `gway:execute`
   grant is ever issued by this process.**

## Commands (design / not yet accepted for production)

On gway-001, generate a key file with mode 0600:

```sh
python3 -m gway_remote.sd_card_key --output /protected/gway-014-installation.pem
```

This prints the public key only. Transmit it to the authorized Watchtower
operator through the existing authenticated administrative route (not over a
public endpoint). On Watchtower, an authorized root operator creates an
unshared sealing key once and prepares the matching node:

```sh
python3 -m gway_remote.deferred_enrollment_cli \
  --ledger /protected/enrollment.sqlite \
  --sealing-key /etc/gway-remote/sd-sealing.key init-key

python3 -m gway_remote.deferred_enrollment_cli \
  --ledger /protected/enrollment.sqlite \
  --sealing-key /etc/gway-remote/sd-sealing.key \
  prepare --node gway-014 --public-key PUBLIC_KEY_FROM_GWAY001
```

The ledger path is intentionally illustrative: use the actual active
Watchtower enrollment SQLite path, never make a second authority. The operator
returns only the nonsecret preparation ID. On gway-001, identify the SD with
`lsblk` and `findmnt` before preview and commit:

```sh
python3 -m gway_remote.sd_inject --bootfs /media/bootfs \
  --node gway-014 --installer arthe \
  --preparation-id PREPARATION_ID \
  --private-key-file /protected/gway-014-installation.pem

# Only after independent device identity and config checks:
python3 -m gway_remote.sd_inject --bootfs /media/bootfs \
  --node gway-014 --installer arthe \
  --preparation-id PREPARATION_ID \
  --private-key-file /protected/gway-014-installation.pem --commit
```

The write creates a 0700 host-side backup; retain it, verify written hashes,
safely unmount the card, then cold boot the target. The injector does not
unmount automatically. On Watchtower **the HTTP challenge/claim routes are
off by default**. An explicit `GWAY_SD_PREPARATIONS_ENABLED=1` environment
setting, plus the root-owned 0600 sealing key at the path above, is required
for the existing loopback enrollment service to enable them. No setting has
been changed on Watchtower.

Operator status and revocation:

```sh
python3 -m gway_remote.deferred_enrollment_cli --ledger /protected/enrollment.sqlite \
  --sealing-key /etc/gway-remote/sd-sealing.key status --id PREPARATION_ID
python3 -m gway_remote.deferred_enrollment_cli --ledger /protected/enrollment.sqlite \
  --sealing-key /etc/gway-remote/sd-sealing.key revoke --id PREPARATION_ID
```

## Security / operational limits

- **A microSD is cloneable.** A copied pre-boot card includes the private key
  in the Imager FAT cloud-config; first-claim-wins prevents two competing
  first claims but does not give hardware-backed identity assurance. Removing
  the secret from the root filesystem after successful bootstrap is not a
  secure erasure of the original FAT sectors.
- Watchtower session sealing key must remain root-owned, mode 0600, and persist
  across restarts. Its loss prevents idempotent recovery of claimed sessions.
- A personally issued Raspberry Pi Connect auth key may expire after 6 hours,
  regardless of the 24-hour GWay preparation. The injector cannot renew an
  expired personal Connect key on its own.
- The existing 15-minute manual invitation remains unchanged. This code
  creates a deferred-specific two-hour session only after signed claim.
- FAT rename and fsync are **not power-fail atomic**. A staged file and protected
  backup are not yet a tested recovery journal; test power interruptions before
  any non-canary use.
- The service requires network access and a supported Pi OS image with
  `python3-cryptography` available from its package mirror. It retries on
  failures without resetting Watchtower's deadlines.
- Server-side loopback is necessary but not sufficient for public security:
  confirm reverse-proxy route exposure, request rate-limiting, and authorization
  of root-only management. Do not activate on production without review.
- No remote `exec grant`, Watchtower deployment, gway-001 deployment or
  hardware installation is performed by this PR.

## Acceptance still required

Hermetic tests cover Ed25519 proof, wrong key, challenge expiry, concurrency,
revocation, reissue, fresh signed retries, nonsecret status and cloud-init
preservation. Next acceptance step: validate the exact Trixie/Imager cloud-init
format on a clean gway-014 card, offline→online retry, Connect login without
SSH, WireGuard enrollment and remote verification, failed power-cycle recovery,
server-side rate limits and authorization. Keep Draft until complete.
