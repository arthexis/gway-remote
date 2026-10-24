#!/usr/bin/env bash
# Install only the satellite WireGuard client from this checked-out repository.
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo/root" >&2
  exit 1
fi
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source_file="$here/gway_remote/wireguard_satellite.py"
test -f "$source_file"
command -v python3 >/dev/null
command -v wg >/dev/null
command -v wg-quick >/dev/null
command -v systemctl >/dev/null
install -d -m 0755 /usr/local/lib/gway-remote-satellite
install -m 0644 "$source_file" /usr/local/lib/gway-remote-satellite/wireguard_satellite.py
cat >/usr/local/bin/gway-remote-wire <<'EOF'
#!/usr/bin/env bash
exec python3 /usr/local/lib/gway-remote-satellite/wireguard_satellite.py "$@"
EOF
chmod 0755 /usr/local/bin/gway-remote-wire
echo "Installed standalone gway-remote-wire (bootstrap/status). No tunnel changed."
