#!/bin/sh
# Opt-in switch of the existing user service to the private WireGuard address.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as operator, not root" >&2; exit 1; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
command -v ip >/dev/null
ip -4 addr show dev gway | grep -q '10\.90\.0\.2/' || { echo "WireGuard address 10.90.0.2 missing" >&2; exit 1; }
test -f "$HOME/.config/gway-remote/mobile-api.env" || { echo "First run sh scripts/install-mobile-api.sh" >&2; exit 1; }
test -x /usr/local/bin/gway-remote || { echo "CLI missing" >&2; exit 1; }
UNIT="$HOME/.config/systemd/user/gway-remote-mobile-api.service"
mkdir -p "$(dirname "$UNIT")"
if [ -f "$UNIT" ]; then
  grep -Eq '^ExecStart=/usr/local/bin/gway-remote api --host (127\.0\.0\.1|10\.90\.0\.2) --port 8765$' "$UNIT" || {
    echo "Existing unit differs from managed service; refusing overwrite" >&2; exit 1;
  }
fi
install -m 644 "$ROOT/deploy/systemd/user/gway-remote-mobile-api-wireguard.service" "$UNIT"
systemctl --user daemon-reload
echo "Installed WireGuard-only unit; service NOT started or enabled by this script."
echo "Ensure host firewall denies public port 8765, then: systemctl --user enable --now gway-remote-mobile-api.service"
