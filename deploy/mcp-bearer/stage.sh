#!/bin/sh
# Opt-in Watchtower stage. No service activation.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo" >&2; exit 1; }
[ -f ./deploy/mcp-bearer/gway-mcp-gateway.service ] || exit 1
getent group gway-mcp-read >/dev/null || groupadd --system gway-mcp-read
id gway-mcp-auth >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gway-mcp-auth --shell /usr/sbin/nologin -g gway-mcp-read gway-mcp-auth
id gway-mcp-gateway >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin -g gway-mcp-read gway-mcp-gateway
install -d -o gway-mcp-auth -g gway-mcp-read -m 0750 /var/lib/gway-mcp-auth
install -d -o root -g root -m 0755 /etc/gway-mcp-gateway
install -m 0644 ./deploy/mcp-bearer/gway-mcp-gateway.service /etc/systemd/system/gway-mcp-gateway.service
systemctl daemon-reload
echo "STAGED only; no activation, credentials or Nginx changes"
