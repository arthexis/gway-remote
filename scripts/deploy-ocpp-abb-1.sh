#!/usr/bin/env bash
# GitHub runner gway-001 -> existing pinned SSH alias -> ocpp-abb-1.
# Only two fixed, repository-owned deployment entrypoints are permitted.
set -euo pipefail

if [[ $# != 2 ]]; then
  echo "usage: deploy-ocpp-abb-1.sh {ocpp-csms|ocpp-reports} {preview|deploy}" >&2
  exit 2
fi
repo="$1"; mode="$2"
case "$repo" in ocpp-csms|ocpp-reports) ;; *) echo "Unapproved repository" >&2; exit 2 ;; esac
case "$mode" in preview|deploy) ;; *) echo "Invalid mode" >&2; exit 2 ;; esac
[[ "$(hostname -s)" == "gway-001" ]] || { echo "Requires gway-001 runner" >&2; exit 2; }

# SSH reads use the pre-existing operator SSH config, with host-key checks enabled.
# The remote script owns all paths/commands, never accepts a caller-supplied path.
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 ocpp-abb-1 \
  "bash -s -- '$repo' '$mode'" <<'REMOTE'
set -euo pipefail
repo="$1"; mode="$2"
[[ "$(hostname -s)" == "ocpp-abb-1" ]] || { echo "Wrong deployment host" >&2; exit 2; }
[[ "$(id -un)" == "ubuntu" ]] || { echo "Wrong deployment identity" >&2; exit 2; }
case "$repo" in ocpp-csms|ocpp-reports) ;; *) exit 2 ;; esac
case "$mode" in preview|deploy) ;; *) exit 2 ;; esac
checkout="/home/ubuntu/Repos/$repo"
[[ -d "$checkout/.git" && ! -L "$checkout" ]] || { echo "Missing trusted checkout" >&2; exit 2; }
cd "$checkout"
[[ "$(git remote get-url origin)" == "https://github.com/arthexis/$repo" ||
   "$(git remote get-url origin)" == "https://github.com/arthexis/$repo.git" ]] ||
  { echo "Unexpected Git origin" >&2; exit 2; }
[[ "$(git branch --show-current)" == "main" ]] || { echo "Checkout is not on main" >&2; exit 2; }
[[ -z "$(git status --porcelain)" ]] || { echo "Dirty checkout; refusing" >&2; exit 2; }
[[ -x ./deploy.sh ]] || { echo "Missing repository deploy.sh" >&2; exit 2; }
printf 'target=%s repo=%s mode=%s checkout_sha=%s\n' \
  "$(hostname -s)" "$repo" "$mode" "$(git rev-parse HEAD)"
if [[ "$mode" == "preview" ]]; then
  systemctl is-active ocpp-csms.service || true
  systemctl is-active ocpp-reports-collector.service || true
  systemctl is-active ocpp-reports-dashboard-admin.service || true
  exit 0
fi
# Serialize between different repositories in addition to their per-app locks.
exec 9>/home/ubuntu/.local/state/ocpp-abb-1-deploy.lock
flock -n 9 || { echo "Another OCPP deployment is running" >&2; exit 3; }
git fetch --no-tags origin refs/heads/main
git merge --ff-only FETCH_HEAD
printf 'deploying_sha=%s\n' "$(git rev-parse HEAD)"
if [[ "$repo" == "ocpp-reports" ]]; then
  ./deploy.sh --watchtower
  systemctl is-active --quiet ocpp-reports-collector.service
  systemctl is-active --quiet ocpp-reports-dashboard-admin.service
  systemctl is-active --quiet ocpp-reports-ingest.service
else
  ./deploy.sh
  systemctl is-active --quiet ocpp-csms.service
fi
# The runtime release pointer, not Git HEAD alone, proves activation.
sha="$(git rev-parse HEAD)"
if [[ "$repo" == "ocpp-reports" ]]; then
  installed="$(readlink -f /opt/ocpp-reports/current)"
  [[ "$installed" == "/opt/ocpp-reports/releases/${sha}-pkg" ]] ||
    { echo "Reports active release does not match source SHA" >&2; exit 4; }
else
  installed="$(readlink -f /home/ubuntu/.local/share/ocpp-csms/current)"
  [[ "$installed" == "/home/ubuntu/.local/share/ocpp-csms/releases/${sha:0:12}" ]] ||
    { echo "CSMS active release does not match source SHA" >&2; exit 4; }
fi
printf 'deployment_completed repo=%s installed_sha=%s\n' "$repo" "$sha"
REMOTE
