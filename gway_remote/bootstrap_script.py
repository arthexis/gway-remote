"""Pure renderer of the HTTPS bootstrap shell artifact.

Keep this separate from HTTP transport and the enrollment ledger. The
standalone client is still served unchanged and must not import the package.
Render is pure: it does not install, enroll, connect or reveal a token in logs.
"""
from __future__ import annotations

import base64
import re


def render_bootstrap_script(secret: str, device: str, server_key: str,
                            *, repair_host_identity: bool = False,
                            release_revision: str, relay_public_key: str,
                            client_sha256: str) -> bytes:
    """Render bounded one-URL provisioning; all release inputs must be reviewed."""
    if not isinstance(release_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", release_revision):
        raise ValueError("missing exact reviewed revision")
    if not isinstance(client_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", client_sha256):
        raise ValueError("missing reviewed standalone client digest")
    if not isinstance(relay_public_key, str) or not re.fullmatch(
            r"ssh-ed25519 [A-Za-z0-9+/=]{40,128}", relay_public_key):
        raise ValueError("missing existing Watchtower relay public key")
    relay_b64 = base64.b64encode((relay_public_key + "\n").encode("ascii")).decode("ascii")
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
apt-get install -y -qq python3 curl wireguard-tools git ansible openssh-server sudo
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT HUP INT TERM
# The standalone client is bound to the exact installed Watchtower package.
curl -fsS --proto '=https' --max-redirs 0 'https://register.gelectriic.com/v1/bootstrap/{secret}/client.py' -o "$temp/client.py"
printf '%s  %s\n' '{client_sha256}' "$temp/client.py" | sha256sum -c - >/dev/null
# Git's object hash binds the rest of the package, playbook and scripts. Never
# follow a moving branch or execute from an unreviewed checkout.
mkdir "$temp/source"
git -C "$temp/source" init -q
git -C "$temp/source" remote add origin https://github.com/arthexis/gway-remote.git
GIT_TERMINAL_PROMPT=0 git -C "$temp/source" -c protocol.file.allow=never fetch -q --no-tags --depth=1 origin '{release_revision}'
git -C "$temp/source" checkout -q --detach FETCH_HEAD
if [ "$(git -C "$temp/source" rev-parse HEAD)" != '{release_revision}' ]; then
  echo 'bootstrap release mismatch' >&2; exit 1
fi
if [ -n "$(git -C "$temp/source" status --porcelain --untracked-files=all -- gway_remote ansible scripts)" ]; then
  echo 'unreviewed bootstrap source' >&2; exit 1
fi
# Public-only SSH relay key from Watchtower's established pinned identity.
printf '%s' '{relay_b64}' | base64 -d > "$temp/relay.pub"
chmod 0600 "$temp/relay.pub"
if [ "$#" -eq 2 ]; then override="$2"; else override=""; fi
python3 "$temp/source/scripts/build-bootstrap-vars.py" \
  --node '{device}' --revision '{release_revision}' \
  --relay-key-file "$temp/relay.pub" --executor-user "$override" > "$temp/vars.json"
printf '%s' '{secret}' > "$temp/session"
python3 "$temp/client.py" bootstrap --device '{device}' --server-public-key '{server_key}' --token-file "$temp/session"{' --repair' if repair_host_identity else ''} "$@"
ansible-playbook -i localhost, -c local "$temp/source/ansible/bootstrap-node.yml" \
  --extra-vars "@$temp/vars.json"
# A local receipt does not imply Watchtower grant or a terminal MCP result.
pub="$(wg show gway public-key)"
printf '{{"device":"%s","public_key":"%s","revision":"%s","stages":["wireguard","package","user_manager","restricted_relay","receiver"]}}' '{device}' "$pub" '{release_revision}' > "$temp/ack.json"
curl -fsS --proto '=https' --max-redirs 0 -X POST -H 'Content-Type: application/json' --data-binary @"$temp/ack.json" 'https://register.gelectriic.com/v1/bootstrap/{secret}/complete' -o "$temp/complete.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("complete") is True and d.get("local_setup_reported") is True and d.get("local_ready_verified") is False; print("LOCAL_SETUP_REPORTED; WATCHTOWER_GRANT_AND_LIMITS_REQUIRED; REMOTE_EXECUTION_UNVERIFIED")' "$temp/complete.json"
"""
    return source.encode("utf-8")
