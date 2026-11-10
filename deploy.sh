#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(id -u)" -eq 0 ]; then
  echo "Run as the GWAY operator, not root." >&2
  exit 1
fi
command -v ansible-playbook >/dev/null 2>&1 || {
  echo "ansible-playbook is required; on Ubuntu 22.04 install it with: sudo apt install ansible-core" >&2
  exit 1
}
ansible_version=$(ansible-playbook --version 2>/dev/null | awk '
  NR == 1 && match($0, /(core |ansible-playbook )[0-9]+\.[0-9]+/) {
    version = substr($0, RSTART, RLENGTH)
    sub(/^(core |ansible-playbook )/, "", version)
    print version
    exit
  }
')
ansible_major=${ansible_version%%.*}
ansible_minor=${ansible_version#*.}
if [ -z "$ansible_version" ] ||
   [ "$ansible_major" -lt 2 ] ||
   { [ "$ansible_major" -eq 2 ] && [ "$ansible_minor" -lt 12 ]; }; then
  printf '%s\n' "Ansible Core 2.12 or newer is required (detected: ${ansible_version:-unknown})." >&2
  printf '%s\n' "On Ubuntu 22.04 use: sudo apt install ansible-core (not the ansible metapackage)." >&2
  exit 1
fi
# Opt-in immutable staging only: do not change the installed zipapp or Mobile API.
if [ "${1:-}" = "--stage-release" ]; then
  shift
  if [ "$#" -ne 0 ]; then
    echo "Usage: ./deploy.sh --stage-release" >&2
    exit 2
  fi
  state_dir="$HOME/.local/state/gway-remote"
  if [ -L "$HOME/.local/state" ] || [ -L "$state_dir" ]; then
    echo "Unsafe GWay Remote deployment state directory" >&2
    exit 2
  fi
  (umask 077; mkdir -p "$state_dir")
  if [ -L "$state_dir/deploy.lock" ]; then
    echo "Unsafe GWay Remote deployment lock" >&2
    exit 2
  fi
  (umask 077; : >> "$state_dir/deploy.lock")
  exec 9<>"$state_dir/deploy.lock"
  if ! flock -n 9; then
    echo "GWay Remote stage operation already running" >&2
    exit 3
  fi
  exec ansible-playbook "$ROOT/ansible/playbooks/stage-release.yml" -i localhost, -c local
fi

# On a Watchtower with an already provisioned and enabled private OAuth link,
# converge its isolated MCP release through Ansible before the ordinary
# same-revision fast path. Do not infer Watchtower from a hostname.
if [ "${GWAY_REMOTE_SKIP_MCP:-0}" != "1" ] &&
   [ -f /etc/gway-mcp-gateway/link.env ] &&
   [ -f /etc/systemd/system/gway-mcp-link.service ] &&
   systemctl is-enabled --quiet gway-mcp-link.service; then
  state_dir="$HOME/.local/state/gway-remote"
  if [ -L "$HOME/.local/state" ] || [ -L "$state_dir" ] ||
     [ -L "$state_dir/deploy.lock" ]; then
    echo "Unsafe GWay Remote MCP deployment lock path" >&2
    exit 2
  fi
  (umask 077; mkdir -p "$state_dir")
  (umask 077; : >> "$state_dir/deploy.lock")
  exec 9<>"$state_dir/deploy.lock"
  flock -n 9 || { echo "GWay Remote deployment/prune already running" >&2; exit 3; }
  ansible-playbook "$ROOT/ansible/playbooks/watchtower-mcp.yml" -i localhost, -c local
fi

# Fast-path identity comes only from the root-owned installed policy, never
# environment variables or an operator-writable checkout. Missing policy
# disables the fast path so Ansible can provision it during bootstrap.
verify_node_worker_import() {
  node_name=$(hostname -s) || return 1
  if ! printf '%s\n' "$node_name" | grep -Eq '^gway-[0-9]+$'; then
    return 0
  fi
  selected=$(/usr/bin/python3 -c '
import json, os, pwd, stat, sys
p = "/etc/gway-remote/executor-identity.json"
try:
    d = os.open("/etc/gway-remote", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(d)
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("unsafe identity directory")
        fd = os.open("executor-identity.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=d)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("unsafe identity policy")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(1025)
            if len(raw) > 1024:
                raise ValueError("oversized identity policy")
            obj = json.loads(raw)
            if type(obj) is not dict or set(obj) != {"user"}:
                raise ValueError("invalid identity policy")
            user = obj["user"]
            if type(user) is not str or not user or user == "root":
                raise ValueError("invalid executor user")
            if pwd.getpwnam(user).pw_uid == 0:
                raise ValueError("root executor denied")
            print(user)
        finally:
            os.close(fd)
    finally:
        os.close(d)
except (OSError, ValueError, TypeError, KeyError):
    sys.exit(1)
' "$node_name") || return 1
  # The installer must never validate a worker by switching to another
  # Unix account. A conflicting installed identity fails closed and forces
  # the explicit migration path instead of an implicit sudo -u transition.
  [ "$selected" = "$(id -un)" ] || return 1
  env PYTHONPATH=/opt/gway-remote /usr/bin/python3 -c 'import gway_remote.node_exec_worker' >/dev/null 2>&1
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
   systemctl is-active --quiet gway-remote-watch.timer &&
   verify_node_worker_import; then
  if [ -n "${GWAY_REMOTE_DEPLOY_NOOP_FILE:-}" ]; then
    printf 'skipped\n' > "$GWAY_REMOTE_DEPLOY_NOOP_FILE"
  fi
  printf 'GWay Remote revision %s already installed and healthy; skipped Ansible.\n' "$revision"
  exit 0
fi
ansible-playbook "$ROOT/ansible/playbook.yml" -i 'gway_remote,' -c local \
  -e "gway_remote_runner_user=$(id -un)" \
  -e "gway_remote_runner_uid=$(id -u)" "$@"
# Only the ordinary managed deployment can certify the default installation.
if [ "$#" -eq 0 ]; then
  mkdir -p "$(dirname "$marker")"
  tmp=$(mktemp "${marker}.XXXXXX")
  printf '%s\n' "$revision" > "$tmp"
  mv -f "$tmp" "$marker"
fi
