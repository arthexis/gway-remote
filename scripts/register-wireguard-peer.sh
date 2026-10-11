#!/bin/sh
# Run on the Lightsail WireGuard hub, from the gway-remote repository.
# Registers an existing peer without generating keys or restarting the tunnel.
set -eu
umask 077

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PLAYBOOK="$ROOT/ansible/playbooks/adopt-wireguard-peer.yml"
INTERFACE=gway

if [ "$(id -u)" -eq 0 ]; then
  echo "Run as the regular Ubuntu operator (sudo is invoked only for Ansible)." >&2
  exit 1
fi
for cmd in ansible-playbook sudo wg python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing dependency: $cmd" >&2; exit 1; }
done
sudo -n wg show "$INTERFACE" public-key >/dev/null || {
  echo "Existing WireGuard interface '$INTERFACE' is unavailable." >&2
  exit 1
}
if [ "$#" -ne 0 ]; then
  echo "Usage: sh scripts/register-wireguard-peer.sh (paste public key when prompted)" >&2
  exit 2
fi
printf 'GWay-001 public key (from: sudo wg show gway public-key): '
IFS= read -r PUBLIC_KEY || { echo "No public key received." >&2; exit 1; }
case "$PUBLIC_KEY" in
  *[!A-Za-z0-9+/=]*|'') echo "Invalid public key characters." >&2; exit 1 ;;
esac
if [ "${#PUBLIC_KEY}" -ne 44 ]; then
  echo "WireGuard public key must be 44 characters." >&2
  exit 1
fi
printf 'Register GWay-001 (10.90.0.2/32) on this server? [y/N] '
IFS= read -r CONFIRM || exit 1
case "$CONFIRM" in y|Y|yes|YES) ;; *) echo "Cancelled."; exit 0 ;; esac
# Keep the public key out of the process command line and shell history.
# Ansible reads JSON extra vars from a mode-0600 temporary file.
TMP=$(mktemp)
INV=$(mktemp)
trap 'rm -f "$TMP" "$INV"' EXIT HUP INT TERM
printf '[wireguard_hub]\nlocalhost ansible_connection=local\n' > "$INV"
python3 -c 'import json,sys; json.dump({"gway_wg_peer_public_key":sys.argv[1]},open(sys.argv[2],"w"))' "$PUBLIC_KEY" "$TMP"
if ! sudo -n true; then
  echo "Non-interactive sudo is unavailable; check the ubuntu user sudo policy." >&2
  exit 1
fi
ANSIBLE_BECOME_FLAGS="-n" ansible-playbook -i "$INV" "$PLAYBOOK" -e "@$TMP"
echo "Peer configured. From GWay-001, initiate traffic to 10.90.0.1 and check latest-handshakes."
