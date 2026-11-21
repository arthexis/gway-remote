"""Pure renderer of the HTTPS bootstrap shell artifact.

Keep this separate from HTTP transport and the enrollment ledger. The
standalone client is still served unchanged and must not import the package.
Render is pure: it does not install, enroll, connect or reveal a token in logs.
"""
from __future__ import annotations


def render_bootstrap_script(secret: str, device: str, server_key: str,
                            *, repair_host_identity: bool = False) -> bytes:
    """Return the established stage-one shell bytes, without side effects."""
    source = f"""#!/bin/sh
set -eu
umask 077
if [ "$(id -u)" != 0 ]; then echo 'bootstrap requires root' >&2; exit 1; fi
# Never bootstrap the Watchtower enrollment owner as a satellite.
if [ -e /etc/gway-remote/watchtower.json ] || [ -e /etc/systemd/system/gway-remote-watchtower.service ]; then
  echo 'refusing satellite bootstrap on Watchtower' >&2
  exit 1
fi
# A copied bearer must not silently enroll the wrong node.
if [ "$(hostname -s)" != '{device}' ]; then
  echo 'satellite bootstrap target hostname mismatch' >&2
  exit 1
fi
# An override is accepted only as an explicit provisioning argument.
if [ "$#" -ne 0 ] && {{ [ "$#" -ne 2 ] || [ "$1" != "--executor-user" ]; }}; then
  echo 'usage: bootstrap [--executor-user EXISTING_NON_ROOT_ACCOUNT]' >&2
  exit 2
fi
# Host-identity repair is identity-neutral: keep root-only repair supported.
if [ "{'1' if repair_host_identity else '0'}" = "1" ] && [ "$#" -ne 0 ]; then
  echo 'host identity repair does not accept executor override' >&2
  exit 2
fi
if [ "$#" -eq 0 ] && [ -z "${{SUDO_USER:-}}" ] && [ "{'1' if repair_host_identity else '0'}" != "1" ]; then
  echo 'bootstrap requires sudo origin or --executor-user' >&2
  exit 2
fi
command -v apt-get >/dev/null || {{ echo 'unsupported distribution' >&2; exit 1; }}
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 curl wireguard-tools
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT HUP INT TERM
curl -fsS --proto '=https' --max-redirs 0 'https://register.gelectriic.com/v1/bootstrap/{secret}/client.py' -o "$temp/client.py"
printf '%s' '{secret}' > "$temp/session"
python3 "$temp/client.py" bootstrap --device '{device}' --server-public-key '{server_key}' --token-file "$temp/session"{' --repair' if repair_host_identity else ''} "$@"
pub="$(wg show gway public-key)"
printf '{{"device":"%s","public_key":"%s"}}' '{device}' "$pub" > "$temp/ack.json"
curl -fsS --proto '=https' --max-redirs 0 -X POST -H 'Content-Type: application/json' --data-binary @"$temp/ack.json" 'https://register.gelectriic.com/v1/bootstrap/{secret}/complete' >/dev/null
"""
    return source.encode("utf-8")
