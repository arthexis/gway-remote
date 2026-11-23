# SD injector and Raspberry Pi Connect — staged #682

This branch supplies a **Connect-only first slice**, not complete GWay/WireGuard
deferred enrollment. The existing 15-minute bootstrap URL cannot safely be
embedded in cards that may remain powered off for 24 hours. The separate
Watchtower preparation/claim API, installer keypair and challenge verification
specified by #682 still need implementation before claiming end-to-end success.

## Intended usage (on gway-001)

1. Burn an official **clean** Raspberry Pi OS image on Windows with Raspberry Pi
   Imager. Configure the actual non-root installer, network, SSH, hostname,
   Raspberry Pi Connect auth key, and allow Imager to write its cloud-init
   configuration.
2. Mount only the microSD's FAT bootfs on gway-001. Identify it independently
   using `lsblk` and `findmnt` first; do not expose an internal disk.
3. Preview:

   `python3 -m gway_remote.sd_inject --node gway-014 --installer arthe --bootfs /media/bootfs`

4. Only after confirming the target and preview, write using the same command
   with `--commit`. The injector rejects non-removable devices, an unknown
   filesystem, a changed hostname, missing cloud-config, symlinks, a repeated
   injection and an existing staging file.

The injector uses PyYAML (required for writing cloud-init safely) and emits no
auth key or bootstrap token. It adds a root-owned first-boot POSIX script via
`write_files` and a single `runcmd` entry, preserving the existing Imager
`runcmd`, `users`, SSH and network settings.

The script enables `rpi-connect.service`,
`rpi-connect-signin.path` and logind lingering for the installer account.
It **does not** invoke `rpi-connect signin`, replace the Imager auth key,
install an unsupported package, or enable GWay execute permissions. It fails
with sanitized logs if installed Connect units or the user manager are missing.
Automatic sign-in still requires a valid auth key, working networking and
compatible versions of Raspberry Pi OS/Imager/Connect.

## Boundaries and unverified acceptance

- FAT does not guarantee crash-atomic file replacement. A protected backup is
  retained on the injector host; the write must be followed by physical
  checksum, unmount and power-loss testing before a production approval.
- This first slice does not yet integrate with Watchtower issuance or establish
  WireGuard. It must not be used as a complete satellite enrollment procedure.
- The preconfigured personal Connect auth key typically has a much shorter
  lifetime than the intended 24-hour GWay preparation window.
- No software-only token stored on FAT proves hardware identity or prevents
  bit-for-bit SD cloning.
- Physical acceptance must check that Connect appears in the right account
  after a cold boot without SSH login, and distinguishes remote shell from
  desktop screen sharing.
- Before any runtime roll-out: add the authenticated Watchtower deferred
  preparation contract, power-loss recovery, device mount conflict detection,
  root/active partition rejection, secret-safe receipts and end-to-end tests.
