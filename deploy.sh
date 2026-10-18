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
exec ansible-playbook "$ROOT/ansible/playbook.yml" -i 'gway_remote,' -c local "$@"
