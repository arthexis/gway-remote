#!/bin/sh
# Explicit, serialized operator activation; never called by auto-deploy.
set -eu
umask 077
[ "$#" -eq 2 ] || { echo 'usage: watchtower-routing-activate.sh SHA MODE' >&2; exit 2; }
sha=$1
mode=$2
case "$sha" in *[!0-9a-f]*|'') exit 2;; esac
[ "${#sha}" -eq 40 ] || exit 2
case "$mode" in legacy|canonical-with-aliases|canonical) ;; *) exit 2;; esac
[ "$(id -un)" = ubuntu ] && [ "$(id -u)" -ne 0 ] || exit 2
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
[ "$(git -C "$root" rev-parse HEAD)" = "$sha" ] || exit 2
[ -z "$(git -C "$root" status --porcelain)" ] || exit 2
state="$HOME/.local/state/gway-remote"
[ ! -L "$HOME/.local" ] && [ ! -L "$HOME/.local/state" ] && [ ! -L "$state" ] || exit 2
[ -f "$state/deploy.lock" ] && [ ! -L "$state/deploy.lock" ] || exit 2
exec 9<>"$state/deploy.lock"
flock -n 9 || { echo 'Watchtower deployment already running' >&2; exit 3; }
ansible-playbook -i localhost, -c local "$root/ansible/playbooks/watchtower-mcp-node-routing.yml" \
    -e "mcp_routing_revision=$sha" -e "mcp_routing_mode=$mode"
