#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -m 755 "$TMP/source" "$TMP/source/gway_remote"
# Copy contents, not the package symlink: archive-backed deployments use
# /opt/gway-remote/gway_remote -> .package-releases/<digest>/gway_remote.
cp -R "$ROOT/gway_remote/." "$TMP/source/gway_remote/"
printf 'from gway_remote.__main__ import main\nmain()\n' > "$TMP/source/__main__.py"
python3 -m zipapp "$TMP/source" -p '/usr/bin/env python3' -o "$TMP/gway-remote"
chmod 755 "$TMP/gway-remote"
if test -w /usr/local/bin; then
  install -m 755 "$TMP/gway-remote" /usr/local/bin/gway-remote
else
  sudo install -m 755 "$TMP/gway-remote" /usr/local/bin/gway-remote
fi
echo 'Installed /usr/local/bin/gway-remote'
# Stage 2 alias is opt-in until controlled deployment review. Do not overwrite
# an unrelated command. The wrapper follows later gway-remote updates.
if [ "${GWAY_INSTALL_FEED_ALIAS:-0}" = 1 ]; then
  printf '#!/bin/sh\nexec /usr/local/bin/gway-remote feed "$@"\n' > "$TMP/feed"
  if test -e /usr/local/bin/feed || test -L /usr/local/bin/feed; then
    if ! test -f /usr/local/bin/feed || test -L /usr/local/bin/feed || ! cmp -s "$TMP/feed" /usr/local/bin/feed; then
      echo 'feed alias already exists; refusing to replace it' >&2
      exit 1
    fi
  elif test -w /usr/local/bin; then
    install -m 755 "$TMP/feed" /usr/local/bin/feed
  else
    sudo install -m 755 "$TMP/feed" /usr/local/bin/feed
  fi
fi
