#!/usr/bin/env bash
# Called only by GWay Remote's existing gway-001 runner.
# gh authentication is local to the node, never copied to GitHub Actions.
set -euo pipefail
[[ "$(id -un)" == arthe ]] || { echo "Expected appliance deployment user" >&2; exit 2; }
checkout="/home/arthe/Repos/gway-webos-tv"
[[ -d "$checkout/.git" ]] || { echo "Missing trusted webOS checkout" >&2; exit 1; }
[[ -z "$(git -C "$checkout" status --porcelain)" ]] || { echo "Refusing dirty webOS checkout" >&2; exit 1; }
main_sha="$(gh api repos/arthexis/gway-webos-tv/branches/main --jq '.commit.sha')"
[[ "$main_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid main SHA" >&2; exit 1; }
# Verify CI for the exact current main commit. A pending/failed run is
# not deployable; the next scheduled check will try again.
ci_state="$(gh api "repos/arthexis/gway-webos-tv/actions/workflows/tests.yml/runs?head_sha=$main_sha&event=push&per_page=20" --jq '[.workflow_runs[] | select(.head_sha == "'$main_sha'")] | sort_by(.created_at) | last | if . == null then "missing" else (.status + ":" + (.conclusion // "pending")) end')"
if [[ "$ci_state" != "completed:success" ]]; then
  echo "::notice::webOS main CI not successful ($ci_state); will retry"
  exit 0
fi
state_dir="/home/arthe/.local/state/gway-webos-tv"
mkdir -p "$state_dir"
marker="$state_dir/auto-deployed-sha"
if [[ -f "$marker" && "$(cat "$marker")" == "$main_sha" ]]; then
  echo "::notice::webOS main $main_sha already deployed; no-op"
  exit 0
fi
git -C "$checkout" fetch --quiet origin main
tip="$(git -C "$checkout" rev-parse refs/remotes/origin/main)"
if [[ "$tip" != "$main_sha" ]]; then
  echo "::notice::main advanced during check; retry later"
  exit 0
fi
git -C "$checkout" switch main
git -C "$checkout" merge --ff-only "$main_sha"
[[ "$(git -C "$checkout" rev-parse HEAD)" == "$main_sha" ]]
(
  cd "$checkout"
  ./deploy.sh
  python3 scripts/auto-tv-deploy.py
)
# Re-check current main before marking success to avoid suppressing a newer release.
if [[ "$(gh api repos/arthexis/gway-webos-tv/branches/main --jq '.commit.sha')" == "$main_sha" ]]; then
  printf '%s\n' "$main_sha" > "$marker.tmp"
  mv "$marker.tmp" "$marker"
fi
echo "::notice::webOS main deployment completed: $main_sha"
