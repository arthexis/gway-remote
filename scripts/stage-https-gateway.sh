#!/bin/sh
# Stage Nginx locations; never modify an existing vhost automatically.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as regular ubuntu operator" >&2; exit 1; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/deploy/nginx/gway-remote-locations.conf"
DEST=/etc/nginx/snippets/gway-remote-locations.conf
command -v nginx >/dev/null
sudo -n test -d /etc/nginx/snippets || { echo "Missing /etc/nginx/snippets" >&2; exit 1; }
if sudo -n test -e "$DEST"; then
  sudo -n cmp -s "$SRC" "$DEST" || { echo "Snippet already exists and differs; manual review required" >&2; exit 1; }
else
  sudo -n install -m 644 "$SRC" "$DEST"
fi
echo "Staged $DEST"
echo "Review existing /etc/nginx/sites-enabled/remote.arthexis.com and TLS settings."
echo "Add this line INSIDE its existing HTTPS server block (do not duplicate):"
echo "    include /etc/nginx/snippets/gway-remote-locations.conf;"
echo "Then run: sudo nginx -t && sudo systemctl reload nginx"
echo "No live Nginx configuration was changed by this script."
