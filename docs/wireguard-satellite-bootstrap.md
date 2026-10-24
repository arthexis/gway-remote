# Satellite WireGuard bootstrap (draft)

This client is part of **gway-remote**, not the deprecated classic GWAY Wire sampler. It imports only Python standard-library modules; the satellite needs Python 3, WireGuard tools and systemd.

The Watchtower enrollment response currently does **not** provide its WireGuard server public key. The client therefore requires that public key to be verified and supplied out of band; do not guess it from HTTPS. The hub tunnel address is currently assumed to be `10.90.0.1/32`, and must be made an explicit server contract or configured verified value before field rollout.

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

**Not field-ready:** This PR is a draft until packaging, full server/client contract compatibility, interruption/retry semantics, installer, and real handshake validation are completed. A successful enrollment HTTP response does not establish WireGuard reachability. Watchtower deployment is separately gated by issue #228.
