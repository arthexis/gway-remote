# Phase C — HTTPS to GWay-001 over the existing WireGuard tunnel

Prerequisite: Phase B is verified: GWay-001 10.90.0.2 can ping Lightsail 10.90.0.1. Do not create another tunnel or web server. This change is deliberately **staged**, not automatically deployed: the production remote.arthexis.com Nginx server block has not been inspected in this repository.

## 1. GWay-001 (operator user)

```sh
sh scripts/install-mobile-api.sh # only if the token/unit have not yet been installed
sh scripts/install-mobile-api-wireguard.sh
```

The second script changes the existing *user* unit to bind to **10.90.0.2:8765**, not 0.0.0.0. It refuses to overwrite an unknown unit. Verify local firewall policy blocks any non-WireGuard access to port 8765 and only the hub (10.90.0.1) can reach the listener. Then opt in:

```sh
systemctl --user enable --now gway-remote-mobile-api.service
systemctl --user status gway-remote-mobile-api.service --no-pager
ss -ltn | grep 8765
```

The private bearer token stays in ~/.config/gway-remote/mobile-api.env (mode 600); never paste it into chat or logs. If the unit fails, inspect `journalctl --user -u gway-remote-mobile-api.service`.

## 2. Lightsail (ubuntu operator)

```sh
sh scripts/stage-https-gateway.sh
sudo nginx -T 2>&1 | grep -n -A 45 -B 8 'server_name remote.arthexis.com'
```

**Review** /etc/nginx/sites-enabled/remote.arthexis.com and its certificate/TLS ownership. Do not overwrite existing production configuration, add another server block, or alter arthexis.com/gelectriic.com. Confirm remote.arthexis.com has a valid certificate and port 443 enabled. Insert the printed `include` line *inside the existing TLS server block only*, after confirming it does not conflict with any existing `location` blocks. The snippet contains explicit allowlisted paths and keeps existing Android paths working on the dedicated hostname. Do not put it in an HTTP (port 80) block or another hostname.

```sh
sudo nginx -t && sudo systemctl reload nginx
```

Test reachability privately first from Lightsail with `curl -i --connect-timeout 3 http://10.90.0.2:8765/api/v1/health`. Expect unauthorized without a bearer token (not a timeout). Test HTTPS from an external client: `curl -i https://remote.arthexis.com/api/v1/health` (expect unauthorized). Then use the Android app with base URL `https://remote.arthexis.com` and the existing bearer token. Never disable certificate validation or expose TCP 8765 publicly.

## Security and rollback

The Nginx snippet proxies **only** health, commands and execute. The backend still authenticates bearer tokens. Do not expose arbitrary URL forwarding or route unknown node IDs. Nginx must terminate valid HTTPS and should not log Authorization headers. The private API listener is bound to the WireGuard address, but **binding alone does not limit which WireGuard peers can connect**: enforce the intended hub-only access using host firewall rules if additional peers are present. Preserve the site's original server block and TLS configuration.

To roll back Nginx, remove only the snippet `include` line, validate `sudo nginx -t`, reload; other websites are unaffected. To roll back the API, `systemctl --user disable --now gway-remote-mobile-api.service`, then reinstall the loopback unit with `sh scripts/install-mobile-api.sh` (it does not restart the service). No WireGuard changes are necessary.

## Verification gate

Phase C is implemented in the repo but **not operationally complete** until the production vhost is inspected, snippet included, API enabled, firewall reviewed, and end-to-end HTTPS authentication tested. No remote deployment is performed by GitHub CI.
