#!/bin/sh
# Opt-in user service installation. No network or service activation.
set -eu
if [ "$(id -u)" -eq 0 ]; then
  echo "Run as the GWay Remote operator, not root" >&2
  exit 1
fi
command -v systemctl >/dev/null
command -v python3 >/dev/null
python3 -c 'import gway_remote.mcp_http' || {
  echo "Install the matching Gway Remote Python package first" >&2
  exit 1
}
CONFIG="$HOME/.config/gway-remote"
UNIT="$HOME/.config/systemd/user"
umask 077
mkdir -p "$CONFIG" "$UNIT"
chmod 700 "$CONFIG"
if [ ! -e "$CONFIG/mcp.env" ]; then
  TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
  printf 'GWAY_MCP_BEARER_TOKEN=%s\n' "$TOKEN" > "$CONFIG/mcp.env"
fi
chmod 600 "$CONFIG/mcp.env"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install -m 644 "$ROOT/deploy/systemd/user/gway-remote-mcp.service" "$UNIT/gway-remote-mcp.service"
systemctl --user daemon-reload
echo "Installed MCP user unit and credentials; service NOT enabled or started."
echo "Check python3 resolves the deployed package for /usr/bin/python3."
echo "When locally validated: systemctl --user enable --now gway-remote-mcp.service"
