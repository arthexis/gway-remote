# SSH host-key attestation for an existing enrolled node

On the **node** (for example, gway-002), run:

```sh
gway-remote host-key
```

This prints the existing SSH ED25519 **host public key** only. It does not
generate, rotate, or export private keys, and does not modify WireGuard.
Independently verify the key and its fingerprint through an approved trusted
channel before trusting it on Watchtower. Merely receiving this text over an
unverified SSH connection is not proof of node identity.

On **Watchtower**, provision the verified public key as one line in a
root-protected regular file, e.g.
`/etc/gway-remote/verified-gway-002-host.pub`. Do not put keys, tokens,
or private material in issues, command-line arguments, or logs. Use the
approved administrative file transfer channel.

Then run:

```sh
sudo gway-remote watchtower attest gway-002 --dry-run
sudo gway-remote watchtower attest gway-002
```

If a different protected file was provisioned, use
`--host-key-file /path/to/verified-host.pub` for both commands.
When the default file is missing, `watchtower attest` exits without
attesting and prints the node-side `gway-remote host-key` instruction.
A supplied file must still satisfy the existing protected-file checks.
Never replace this requirement with `ssh-keyscan` or trust-on-first-use.

`register --repair` is a separate invitation-based legacy repair flow,
not necessary merely to attest an already active WireGuard node.
