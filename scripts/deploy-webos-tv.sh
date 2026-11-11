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
# Legacy auto-deployed-sha may represent a node-only deployment while the TV
# was offline; never reuse it as confirmation of TV installation.
tv_marker="$state_dir/tv-installed-sha"
git -C "$checkout" fetch --quiet origin main
tip="$(git -C "$checkout" rev-parse refs/remotes/origin/main)"
if [[ "$tip" != "$main_sha" ]]; then
  echo "::notice::main advanced during check; retry later"
  exit 0
fi
git -C "$checkout" switch main
git -C "$checkout" merge --ff-only "$main_sha"
[[ "$(git -C "$checkout" rev-parse HEAD)" == "$main_sha" ]]
# The node receipt and TV receipt are independent: an offline TV must
# not block safe node activation or suppress a later TV installation.
(
  cd "$checkout"
  GWAY_WEBOS_EXPECTED_SHA="$main_sha" ./deploy.sh
)
if [[ -f "$tv_marker" && "$(cat "$tv_marker")" == "$main_sha" ]]; then
  echo "::notice::Node $main_sha healthy; TV installation already receipted"
  exit 0
fi
if ( cd "$checkout" && python3 scripts/auto-tv-deploy.py --require-online ); then
  # No receipt if main advanced while the TV was being updated.
  if [[ "$(gh api repos/arthexis/gway-webos-tv/branches/main --jq '.commit.sha')" != "$main_sha" ]]; then
    echo "::warning::webOS main changed during TV update; not recording TV receipt"
    exit 0
  fi
  temp="$state_dir/.tv-installed-sha.$$"
  (umask 077; printf '%s\n' "$main_sha" > "$temp")
  mv -f "$temp" "$tv_marker"
  echo "::notice::webOS node and TV installation completed: $main_sha"
else
  rc=$?
  if [[ "$rc" -eq 10 ]]; then
    echo "::warning::webOS node ready at $main_sha; TV offline, installation pending and will retry"
    exit 0
  fi
  echo "::error::webOS TV installation failed (exit $rc); receipt unchanged"
  exit "$rc"
fi
