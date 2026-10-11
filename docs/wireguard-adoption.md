# Phase B — adopt the existing WireGuard hub

**Do not create another tunnel.** Discovery found `wg-quick@gway` active on both hosts. Lightsail uses `gway = 10.90.0.1/24` on UDP 51820, and GWay-001 uses `gway = 10.90.0.2/32`. The Pi knows the server's public key, but the hub's running configuration has **no peers**, and the Pi has no successful handshake.

## Preconditions

1. Review and merge Phase A separately. Confirm the server is the intended Lightsail host and back up `/etc/wireguard/gway.conf` securely.
2. Check Lightsail UDP 51820 inbound rules and OS firewall. Do not open any API port to the internet.
3. On GWay-001 obtain the **public**, not private, key with `sudo wg show gway public-key`.
4. Confirm the hub has no other peers or legacy management process that would overwrite this configuration.
5. Set an Ansible inventory group `wireguard_hub` containing only the Lightsail host. Do not commit credentials or real host inventory.

## Apply

From the repository root, using an inventory you control:

```sh
ansible-playbook -i /path/to/inventory.ini ansible/playbooks/adopt-wireguard-peer.yml \
  -e "gway_wg_peer_public_key=PUBLIC_KEY_FROM_GWAY_001"
```

The playbook preserves the hub's existing interface and private key, backs up its configuration, adds one persistent peer section and applies it to the live interface with `wg set`. It does not restart WireGuard, touch Nginx, alter firewall rules, generate keys or enable new services. It refuses unexpected existing peer sections on the initial run. **Do not use the override variable on initial adoption.** On subsequent idempotent runs, the managed block already exists; use `-e gway_wg_peer_managed=true` only after inspecting that block and confirming it is the one managed by this playbook.

## Verify

On GWay-001, initiate traffic and inspect handshake:

```sh
ping -c 3 -W 2 10.90.0.1
sudo wg show gway latest-handshakes
sudo wg show gway transfer
```

On Lightsail:

```sh
sudo wg show gway allowed-ips
sudo wg show gway latest-handshakes
```

A recent nonzero handshake on both ends is required. ICMP may be filtered; do not use ping failure alone as evidence of WireGuard failure.

## Recovery

The playbook's `blockinfile` operation saves a timestamped backup of the original configuration. To undo, first identify the public key added and the correct backup. Remove that specific live peer with `sudo wg set gway peer PUBLIC_KEY remove`, then restore the reviewed backup of `/etc/wireguard/gway.conf` (or remove only the managed block). Do not restart the interface or delete unrelated peers. If a runtime update fails after persistence succeeds, investigate before rerunning.

**HTTPS and Android access are not enabled by this phase.**
