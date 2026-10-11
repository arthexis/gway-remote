# Phase A — remote.arthexis.com preflight (read-only)

Goal: reclaim the previously reserved hostname for GWay Remote without interrupting the existing Lightsail websites (`arthexis.com` and `gelectriic.com`).

## Scope

This phase **does not** configure DNS, WireGuard, reverse proxies, firewalls, mobile API listeners, certificates, or systemd units. It does not delete the former GWay deployment. The preflight gathers a minimal non-secret inventory of each machine.

Run on the Lightsail Ubuntu host and on GWay-001 from a trusted shell:

```sh
sh scripts/remote-preflight.sh
```

Review the output before sharing it: listener addresses, hostnames, and proxy filenames may be operationally sensitive. Do not run `wg show all`, dump proxy configs, print token files, or share private keys. The script is read-only and intentionally does not use sudo, so some states may be unavailable.

## Discovery checklist

- [ ] Confirm `remote.arthexis.com` A/AAAA records, authoritative DNS provider and whether any obsolete GWay traffic still uses the name.
- [ ] Confirm Lightsail static public IP, instance identity, external Lightsail firewall and UDP 51820 availability **outside the guest OS**.
- [ ] Identify active HTTPS proxy (Nginx, Caddy, Apache or other) and who owns certificate renewal; inspect virtual-host **names** for collisions without replacing existing sites.
- [ ] Identify existing `remote.arthexis.com` configuration, certificates, services and dependencies; classify each as active, obsolete or unknown.
- [ ] Inspect WireGuard interfaces, routes, subnet collisions and guest firewall on both hosts.
- [ ] Confirm GWay-001 can initiate outbound UDP to Lightsail; confirm operator user and whether the opt-in mobile API service is running.
- [ ] Capture a safe rollback baseline for existing DNS/proxy/firewall configurations before any later mutation.

## Proposed design (not applied)

- Public URL: `https://remote.arthexis.com`
- HTTPS gateway: existing Lightsail web proxy, with explicit node routing to `gway-001`.
- Private network: `10.77.0.0/24` **provisional until subnet collision check**; hub `10.77.0.1`, first peer `10.77.0.2`.
- UDP port: 51820 **proposed**, pending firewall and port review.
- GWay Remote API remains loopback-only until a separate, reviewed WireGuard-bound configuration is introduced.
- All deployment templates and playbooks will live in `arthexis/gway-remote`, not the website repositories.

## Go/no-go gate for Phase B

Proceed only after verifying hostname ownership and unused legacy configuration, the production web proxy and certificate layout, both host routing tables, and a tested recovery path. Unknown old GWay dependencies are **not** authorization to delete them.

No external host inspection is performed by GitHub CI; its tests only validate the preflight script's non-destructive behavior.
