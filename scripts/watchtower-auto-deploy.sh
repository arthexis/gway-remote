#!/bin/sh
# D1: Execute ONLY the existing Watchtower MCP Ansible play from a reviewed
# main revision. Intended as stdin to the already trusted gway-001 -> Watchtower
# operator SSH connection. Never edits an operator's existing Git checkout.
set -eu
umask 077

sha=${1:-}
case "$sha" in
  *[!0-9a-f]*|'') echo "Invalid reviewed revision" >&2; exit 2 ;;
esac
[ "${#sha}" -eq 40 ] || { echo "Reviewed revision must be a full SHA" >&2; exit 2; }
[ "$#" -eq 1 ] || exit 2
[ "$(id -un)" = ubuntu ] || { echo "Unexpected Watchtower operator" >&2; exit 2; }
[ "$(id -u)" -ne 0 ] || { echo "Root deployment caller denied" >&2; exit 2; }

# Fail closed on hosts that were never explicitly provisioned. Do not install
# credentials, create OAuth services or enable any existing disabled service.
[ -f /etc/gway-mcp-gateway/link.env ] || { echo "Watchtower OAuth not provisioned" >&2; exit 2; }
[ -f /etc/systemd/system/gway-mcp-link.service ] || exit 2
[ -L /opt/gway-mcp/current ] || exit 2
systemctl is-enabled --quiet gway-mcp-link.service || exit 2
systemctl is-enabled --quiet gway-mcp-gateway.service || exit 2
sudo -n true || { echo "Unattended existing Ansible sudo unavailable" >&2; exit 2; }
command -v ansible-playbook >/dev/null
command -v git >/dev/null
command -v flock >/dev/null

state="$HOME/.local/state/gway-remote"
[ ! -L "$HOME/.local" ] && [ ! -L "$HOME/.local/state" ] && [ ! -L "$state" ] || {
  echo "Unsafe deployment state path" >&2; exit 2;
}
mkdir -p "$state"
[ ! -L "$state/deploy.lock" ] || { echo "Unsafe deployment lock" >&2; exit 2; }
: >> "$state/deploy.lock"
exec 9<>"$state/deploy.lock"
# Share the same lock used by the existing operator deploy.sh.
flock -n 9 || { echo "Watchtower deployment already running" >&2; exit 3; }

tmp=$(mktemp -d "$state/watchtower-auto.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

# A disposable, pinned checkout avoids modifying a dirty operator checkout.
# This is the reviewed public/private repo URL already used by the operator.
git clone --quiet --depth 1 --single-branch --branch main \
  https://github.com/arthexis/gway-remote.git "$tmp/source"
observed=$(git -C "$tmp/source" rev-parse --verify HEAD)
[ "$observed" = "$sha" ] || {
  echo "Main advanced or does not match reviewed SHA; refusing deployment" >&2
  exit 3
}
git -C "$tmp/source" checkout --quiet --detach "$sha"
[ -z "$(git -C "$tmp/source" status --porcelain)" ] || exit 3

# This existing playbook performs staged activation, checks the OAuth/gateway
# services and restores the previous release pointer/units on failure.
ansible-playbook -i localhost, -c local \
  "$tmp/source/ansible/playbooks/watchtower-mcp.yml"

actual=$(readlink /opt/gway-mcp/current)
[ "$actual" = "releases/$sha" ] || {
  echo "Watchtower current release does not match requested SHA" >&2; exit 1;
}
systemctl is-active --quiet gway-mcp-link.service
systemctl is-active --quiet gway-mcp-gateway.service
# A public OAuth discovery URL is deliberately not involved in this check.
python3 - <<'PY'
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:19012/.well-known/oauth-authorization-server",
             timeout=8) as response:
    result = json.load(response)
assert result["issuer"] == "https://remote.arthexis.com"
assert "S256" in result["code_challenge_methods_supported"]
PY
printf 'watchtower_mcp_revision=%s\n' "$sha"
