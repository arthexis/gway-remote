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


## Public TLS gateway handoff — production diagnosis

The private mobile API runs on GWAY-001 at `10.90.0.2:8765`.
The public TLS name `remote.arthexis.com` previously resolved to
`54.161.177.151` (historical observation, recheck DNS before acting).
Do not assume that Nginx on GWAY-001 serves the public name. The
GWAY-001 `nginx -T` reported only `server_name _`.

The repository's `deploy/nginx/gway-remote-locations.conf` is a
**template** to include inside the actual TLS `server` block; it is
not installed onto the remote gateway by the backend workflow.
It contains the exact GET-only `/api/v1/github-health` and
`/api/v1/nodes/gway-001/github-health` forwarding locations,
preserving the Authorization header.

The collector already produced an available snapshot (five repos), and
unauthenticated `curl -i http://10.90.0.2:8765/api/v1/github-health`
returned the expected JSON HTTP 401. In contrast, the public HTTPS
request returned Nginx's HTML HTTP 404. This points to the public
gateway routing until proven otherwise.

**Agent procedure:** identify the authoritative HTTPS host from current
DNS, hosting inventory, and SSH access. On that host, inspect
`sudo nginx -T` for `server_name remote.arthexis.com`, the
`github-health` location, conflicting includes and upstream addresses.
Check private WireGuard reachability to `10.90.0.2:8765` from the
gateway. Capture only HTTP statuses and redacted headers/bodies;
never disclose bearer tokens. Test `nginx -t` before a narrowly scoped
reload. Verify anonymous public GET yields JSON HTTP 401, then
authenticated GET yields HTTP 200 with five repositories and the
published timestamp. Confirm Android refresh works.

**Debug decisions:**
- HTML 404: wrong virtual host, absent active location, stale proxy
  include or request sent to another Nginx. Confirm using `nginx -T`
  and `curl --resolve` against the verified gateway address.
- JSON 404: inspect the API service version and exact route.
- 401: route reachable; verify the Android *mobile API* bearer token,
  which is distinct from the collector's `GITHUB_TOKEN`.
- 502/504: troubleshoot the gateway's private WireGuard path and
  upstream listener without exposing port 8765 publicly.
- HTTP 200 with `status: unavailable`: inspect collector timer,
  source snapshot, permissions and age, not Nginx routing.
- HTTP 200 with `status: available`: confirm app endpoint base URL,
  scope/filter rendering and fresh cached timestamp.

Do not reconfigure DNS, replace unrelated Nginx vhosts, change TLS
termination, broaden firewall rules, or leak credentials. Host-specific
changes require an operational execution step: merging this document
does not modify production Nginx.
