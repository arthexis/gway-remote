#!/bin/sh
# Read-only Watchtower audit. Prints no environment values, tokens, private keys or inventory.
set -eu
printf 'Watchtower authentik preflight (read-only)\n'
printf 'hostname: '; hostname
printf 'kernel: '; uname -srm
printf 'architecture: '; uname -m
printf 'cpu cores: '; getconf _NPROCESSORS_ONLN || true
printf 'memory (kB):\n'; awk '/^(MemTotal|MemAvailable):/ {print $1, $2}' /proc/meminfo
printf 'filesystem capacity:\n'; df -hP / /var/lib 2>/dev/null | awk 'NR==1 || !seen[$6]++'
printf 'docker availability: '; if command -v docker >/dev/null 2>&1; then docker --version; else echo absent; fi
printf 'compose availability: '; if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then docker compose version; else echo absent; fi
printf 'proxy tooling: '; for tool in nginx caddy apache2 certbot; do if command -v "$tool" >/dev/null 2>&1; then printf '%s=present ' "$tool"; else printf '%s=absent ' "$tool"; fi; done; echo
printf 'listeners (TCP, address and port only):\n'
if command -v ss >/dev/null 2>&1; then ss -lntH | awk '{print $4}' | sort -u; else echo unavailable; fi
printf 'DNS for planned auth domain (public records only):\n'
if command -v getent >/dev/null 2>&1; then getent ahosts auth.gelectriic.com | awk '{print $1}' | sort -u || true; fi
printf 'service existence (not config):\n'
for service in nginx.service docker.service; do
  if command -v systemctl >/dev/null 2>&1; then
    printf '%s: ' "$service"
    systemctl is-active "$service" 2>/dev/null || true
  fi
done
echo 'CHECK MANUALLY: TLS ownership, existing vhosts, storage backup policy, firewall, platform/architecture and upgrade window.'
echo 'NO CHANGES MADE'
