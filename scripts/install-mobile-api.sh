#!/bin/sh
# Explicit opt-in installation for the existing user account.
set -eu
if [ "$(id -u)" -eq 0 ]; then
  echo "Run as the GWay Remote operator, not root" >&2
  exit 1
fi
command -v systemctl >/dev/null
command -v python3 >/dev/null
test -x /usr/local/bin/gway-remote || { echo "Install the CLI first" >&2; exit 1; }
CONFIG="$HOME/.config/gway-remote"
UNIT="$HOME/.config/systemd/user"
umask 077
mkdir -p "$CONFIG" "$UNIT"
chmod 700 "$CONFIG"
if [ ! -e "$CONFIG/mobile-api.env" ]; then
  TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
  printf 'GWAY_REMOTE_API_TOKEN=%s\n' "$TOKEN" > "$CONFIG/mobile-api.env"
fi
chmod 600 "$CONFIG/mobile-api.env"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install -m 644 "$ROOT/deploy/systemd/user/gway-remote-mobile-api.service" "$UNIT/gway-remote-mobile-api.service"
systemctl --user daemon-reload
echo "Installed unit and private token file. NOT enabled or started."
echo "Review network access, then run: systemctl --user enable --now gway-remote-mobile-api.service"
echo "Token file: $CONFIG/mobile-api.env (do not share)"
