#!/bin/sh
# Read-only host inventory. No sudo, secrets, reloads, or config changes.
set -eu
umask 077

section() { printf '\n== %s ==\n' "$1"; }
check() {
  if command -v "$1" >/dev/null 2>&1; then
    printf '%s: installed\n' "$1"
  else
    printf '%s: not found\n' "$1"
  fi
}
service_state() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active "$1" 2>/dev/null || true
  else
    printf 'systemctl unavailable\n'
  fi
}
section "Host identity"
hostname
uname -srm
section "Available software"
for app in nginx caddy apache2 wg wg-quick ss getent ufw firewall-cmd; do check "$app"; done
section "Service states"
for svc in nginx caddy apache2 wg-quick@wg-gway gway-remote-mobile-api; do
  printf '%s: ' "$svc"
  service_state "$svc"
done
section "DNS resolution (public records, if resolver available)"
if command -v getent >/dev/null 2>&1; then
  getent ahostsv4 remote.arthexis.com | awk '!seen[$1]++ {print $1}' || true
fi
section "Listener addresses and ports (no process names)"
if command -v ss >/dev/null 2>&1; then
  ss -H -ltn | awk '$4 ~ /:(80|443|8765)$/ {print $4}' || true
  ss -H -lun | awk '$4 ~ /:51820$/ {print $4}' || true
fi
section "Proxy configuration filenames (not contents)"
for dir in /etc/nginx/sites-enabled /etc/nginx/conf.d /etc/caddy /etc/apache2/sites-enabled; do
  if [ -d "$dir" ]; then
    printf '%s\n' "$dir"
    find "$dir" -maxdepth 1 -type f -o -type l | sort
  fi
done
section "WireGuard interface names (not keys)"
if command -v wg >/dev/null 2>&1; then
  wg show interfaces 2>/dev/null || true
fi
section "Firewall state (no rule modifications)"
if command -v ufw >/dev/null 2>&1; then ufw status 2>/dev/null | head -n 2 || true; fi
if command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --state 2>/dev/null || true; fi
section "Preflight finished — no changes made"
