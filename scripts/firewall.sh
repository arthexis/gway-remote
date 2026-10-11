#!/bin/sh
# Stage or apply the GWay-001 mobile API firewall exception using Ansible.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PLAYBOOK="$ROOT/deploy/ansible/mobile-api-firewall.yml"
HOST="${GWAY_REMOTE_FIREWALL_HOST:-gway-001}"
USER="${GWAY_REMOTE_FIREWALL_USER:-arthe}"
APPLY=false
MODE=auto

usage() {
    cat <<'EOF'
Usage: scripts/firewall.sh [--apply] [--local | --remote] [--host HOST] [--user USER]
  (no flags)     Stage persistent rule without restarting the firewall
  --apply        Restart the existing firewall service and verify the live rule
  --local        Run on this machine without SSH
  --remote       Force SSH even if target matches local hostname
  --host HOST    Target (default: gway-001)
  --user USER    SSH user (default: arthe)
  -h, --help     Show this help

Requires Ansible and sudo access; remote mode also requires SSH.
Applying remotely can interrupt SSH; ensure recovery access first.
EOF
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --apply) APPLY=true; shift ;;
        --local) MODE=local; shift ;;
        --remote) MODE=remote; shift ;;
        --host|--user)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            case "$1" in
                --host) HOST=$2 ;;
                --user) USER=$2 ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
case "$HOST" in
    ''|*[!a-zA-Z0-9._-]*) echo "Invalid host" >&2; exit 2 ;;
esac
case "$USER" in
    ''|*[!a-zA-Z0-9._-]*) echo "Invalid user" >&2; exit 2 ;;
esac
command -v ansible-playbook >/dev/null 2>&1 || { echo "ansible-playbook is required" >&2; exit 1; }
[ -f "$PLAYBOOK" ] || { echo "Missing playbook: $PLAYBOOK" >&2; exit 1; }
if [ "$MODE" = auto ]; then
    LOCAL_HOST=$(hostname -s)
    if [ "$HOST" = "$LOCAL_HOST" ] || [ "$HOST" = localhost ] || [ "$HOST" = 127.0.0.1 ]; then
        MODE=local
    else
        MODE=remote
    fi
fi
if [ "$APPLY" = true ]; then
    echo "Applying existing host firewall on $HOST (possible SSH interruption)"
else
    echo "Staging persistent rule on $HOST (no firewall restart)"
fi
if [ "$MODE" = local ]; then
    echo "Using local Ansible connection (no SSH)"
    exec ansible-playbook -i "localhost," -c local --become \
        "$PLAYBOOK" -e "gway_remote_apply_firewall=$APPLY"
fi
exec ansible-playbook -i "$HOST," -u "$USER" --become \
    "$PLAYBOOK" -e "gway_remote_apply_firewall=$APPLY"
