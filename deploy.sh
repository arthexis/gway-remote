#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(id -u)" -eq 0 ]; then
  echo "Run as the GWAY operator, not root." >&2
  exit 1
fi
command -v ansible-playbook >/dev/null 2>&1 || {
  echo "ansible-playbook is required" >&2
  exit 1
}
# This marker is only a hint: every fast-path check validates live artifacts.
revision=$(git -C "$ROOT" rev-parse --verify HEAD)
marker="$HOME/.local/state/gway-remote/deployed-commit"
if [ "$#" -eq 0 ] &&
   [ "$(cat "$marker" 2>/dev/null || true)" = "$revision" ] &&
   [ -x /usr/local/bin/gway-remote ] &&
   /usr/local/bin/gway-remote status --json | /usr/bin/python3 -c 'import json,sys; assert json.load(sys.stdin)["schema"] == "gway-remote/status/v1"' 2>/dev/null &&
   [ -f /etc/systemd/system/gway-remote-watch.service ] &&
   [ -f /etc/systemd/system/gway-remote-watch.timer ] &&
   systemctl is-enabled --quiet gway-remote-watch.timer &&
   systemctl is-active --quiet gway-remote-watch.timer; then
  printf 'GWay Remote revision %s already installed and healthy; skipped Ansible.\n' "$revision"
  exit 0
fi
ansible-playbook "$ROOT/ansible/playbook.yml" -i 'gway_remote,' -c local "$@"
# Only the ordinary managed deployment can certify the default installation.
if [ "$#" -eq 0 ]; then
  mkdir -p "$(dirname "$marker")"
  tmp=$(mktemp "${marker}.XXXXXX")
  printf '%s\n' "$revision" > "$tmp"
  mv -f "$tmp" "$marker"
fi
