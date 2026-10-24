#!/bin/sh
# Opt-in non-root installation; no service starts, credentials or tunnel created.
set -eu
if [ "$(id -u)" -eq 0 ]; then
  echo "Run as the GWay Remote operator, not root" >&2
  exit 1
fi
command -v tunnel-client >/dev/null || {
  echo "Install official openai/tunnel-client first; verify its version" >&2
  exit 1
}
command -v systemctl >/dev/null
test -f "$HOME/.config/gway-remote/mcp.env" || {
  echo "Install and configure local MCP before the tunnel" >&2
  exit 1
}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CONFIG="$HOME/.config/gway-remote"
UNITS="$HOME/.config/systemd/user"
BIN="$HOME/.local/bin"
umask 077
mkdir -p "$CONFIG" "$UNITS" "$BIN"
chmod 700 "$CONFIG"
chmod 600 "$CONFIG/mcp.env"
if [ ! -e "$CONFIG/tunnel.env" ]; then
  printf '%s\n' '# Populate locally; never commit or paste credentials.' \
    'CONTROL_PLANE_TUNNEL_ID=' 'CONTROL_PLANE_API_KEY=' > "$CONFIG/tunnel.env"
fi
chmod 600 "$CONFIG/tunnel.env"
install -m 700 "$ROOT/scripts/run-mcp-tunnel.sh" "$BIN/gway-run-mcp-tunnel"
install -m 644 "$ROOT/deploy/systemd/user/gway-mcp-tunnel.service" "$UNITS/gway-mcp-tunnel.service"
systemctl --user daemon-reload
echo "MCP tunnel unit installed but NOT started or enabled."
echo "Populate ~/.config/gway-remote/tunnel.env privately, validate with tunnel-client doctor, then enable explicitly."
