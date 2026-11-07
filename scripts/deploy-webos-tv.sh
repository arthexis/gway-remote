#!/usr/bin/env bash
# Fixed webOS deployment workload for the existing gway-001 runner.
set -euo pipefail
[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "Expected main SHA" >&2; exit 2; }
[[ "$(id -un)" == arthe ]] || { echo "Expected appliance deployment user" >&2; exit 2; }
source_sha="$1"
checkout="/home/arthe/Repos/gway-webos-tv"
[[ -d "$checkout/.git" ]] || { echo "Missing trusted webOS checkout" >&2; exit 1; }
[[ -z "$(git -C "$checkout" status --porcelain)" ]] || { echo "Refusing dirty webOS checkout" >&2; exit 1; }
git -C "$checkout" fetch --quiet origin main
tip="$(git -C "$checkout" rev-parse refs/remotes/origin/main)"
if [[ "$tip" != "$source_sha" ]]; then
  echo "::notice::Superseded by a newer main revision; skipping stale deployment"
  exit 0
fi
git -C "$checkout" switch main
git -C "$checkout" merge --ff-only "$source_sha"
[[ "$(git -C "$checkout" rev-parse HEAD)" == "$source_sha" ]]
(
  cd "$checkout"
  ./deploy.sh
  python3 scripts/auto-tv-deploy.py
)
