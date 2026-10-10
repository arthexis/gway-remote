#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -R "$ROOT/gway_remote" "$TMP/gway_remote"
printf 'from gway_remote.__main__ import main\nmain()\n' > "$TMP/__main__.py"
python3 -m zipapp "$TMP" -p '/usr/bin/env python3' -o "$TMP/gway-remote"
chmod 755 "$TMP/gway-remote"
if test -w /usr/local/bin; then
  install -m 755 "$TMP/gway-remote" /usr/local/bin/gway-remote
else
  sudo install -m 755 "$TMP/gway-remote" /usr/local/bin/gway-remote
fi
echo 'Installed /usr/local/bin/gway-remote'
