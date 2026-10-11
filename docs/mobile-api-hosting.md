# Mobile API secure hosting — chunk 3

## Deployment decision

The repository has a local CLI and an Ansible CLI-only role, not a verified existing HTTPS gateway. No public hostname, proxy, certificate, or tunnel is configured by this PR. **Do not claim Android HTTPS access is working yet.**

This PR supplies an opt-in user-systemd unit for the existing loopback-only API and a private token file. It adds no handoff service, queue, database, or proxy. One resident API process is necessary for unattended availability; the unit is not automatically enabled.

## Install on the target node

Install the current `gway-remote` CLI first. As the same non-root account that owns the appliance journal:

```sh
sh scripts/install-mobile-api.sh
systemctl --user cat gway-remote-mobile-api.service
systemctl --user enable --now gway-remote-mobile-api.service
systemctl --user status gway-remote-mobile-api.service
```

The installer creates `~/.config/gway-remote/mobile-api.env` with mode 0600, and the config directory with mode 0700. The secret is not printed. It never overwrites an existing token and does not start or enable the unit. To rotate: stop the unit, replace the token in the file with a new random value, and restart the unit; all clients must then update credentials.

The service is bound to `127.0.0.1:8765`. Verify with `ss -ltn` and an authenticated local request. The unit uses `Restart=on-failure`, `NoNewPrivileges=true` and a restrictive umask. Do not run the API as root.

## Required before phone connectivity

1. Identify and verify an existing HTTPS entry point or private authenticated tunnel. A GitHub Actions runner is not an inbound web gateway.
2. Configure TLS with a trusted certificate, strict forwarding to loopback, and no direct internet exposure of port 8765.
3. Restrict network access and verify client token handling; a tunnel alone is not HTTPS.
4. Verify unauthorized requests, service recovery, request timeouts, and resource use on the real target before enabling remote access.
5. Avoid putting tokens into URL parameters, screenshots, shell history, or logs.

**No production HTTPS route is installed or enabled by this PR.** This is the smallest safe deployment foundation until the real endpoint and network route are confirmed.
