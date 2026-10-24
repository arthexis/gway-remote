# Satellite WireGuard bootstrap (draft)

This client is part of **gway-remote**, not the deprecated classic GWAY Wire sampler. It imports only Python standard-library modules; the satellite needs Python 3, WireGuard tools and systemd.

Watchtower now supplies `server_public_key` and `server_tunnel_ip` in the enrollment response. The client compares the server public key against the independently verified value supplied by the operator, and derives the hub /32 from the response rather than assuming a fixed subnet. A private pending key is written before enrollment so retrying the same invitation retains the same public key; do not delete `gway.conf.pending-key` during recovery.

Example after independently obtaining the Watchtower public key and a short-lived invitation:

```sh
sudo python3 -m gway_remote.wireguard_satellite bootstrap \
  --device gway-004 --server-public-key 'VERIFIED_WATCHTOWER_PUBLIC_KEY'
```

The command prompts for the token without echoing it. An alternative is `--token-file /root/invitation` with permissions 0600. Never put invitation tokens in command arguments, URLs, shell history, logs or issue comments.

The implementation refuses to overwrite an existing config. Its status command is read-only:

```sh
python3 -m gway_remote.wireguard_satellite status
```

**Field gate:** The standalone installer, systemd/Watchtower integration tests, PR CI, and a real handshake/reboot test are still required. Do not assume merging this code constitutes production readiness. A successful enrollment HTTP response does not establish WireGuard reachability. Watchtower deployment is separately gated by issue #228.
