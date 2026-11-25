# Android acceptance and publication (#749)

The trusted main workflow Android release acceptance reports the commit status
Android acceptance on every PR targeting main. Backend-only PRs pass without
APK compilation or physical USB use. Android source and the two Android CI
workflow paths require explicit owner approval, exact head/base, CI, Android
APK, emulator Compose, both pinned canary APK hashes and a physical receipt.

## Operator contract

1. Integrate current main and review. Use a standalone line Release-Issue: #123
   in the PR body for each release-tracked issue. Remove closing keywords
   (including from commits) and sidebar closing links.
2. Dispatch android-acceptance.yml on main with mode=accept, pr_number,
   expected_sha, expected_base, and expected baseline test count (minimum six).
   Set auto_merge=true to authorize the complete lifecycle in one action.
3. Reset defaults to no. RESET_CANARY_ONLY is an explicit authorization to
   discard isolated test-package data on a known signature/version conflict.
   The parent owner dispatch binds PR, revision and reset value. The hardware
   job executes only reviewed main code, never a PR checkout.
4. The coordinator waits for the exact runs, rechecks head/base, CI, receipt
   and issue links, and reports success. It uses native auto-merge only after
   strict gate enforcement and a clean PR. It checks the exact merged revision
   and dispatches publication if the bot merge did not trigger a push run.
   Mixed Android/backend PRs use auto_merge=false and normal operator merge
   to preserve backend deploy triggers. Include the release markers in the
   immutable merge commit body.
5. The publisher downloads the published APK, compares it byte-for-byte to
   the signed build, verifies its signature, tag, commit and API digest,
   then closes explicitly linked issues whose markers match the merge commit.
   Production application data and installed packages are not changed.

## Staged rollout

Merge the reviewed infrastructure PR under existing rules; workflow-only
pushes no longer publish an APK. From a trusted main checkout:

    python3 -m gway_remote.android_acceptance_ruleset --ruleset 24802372

Backfill existing open PRs (before accepting any Android PR):

    python3 -m gway_remote.android_acceptance_ruleset --ruleset 24802372 --backfill

Verify a backend-only success, Android pending, and an owner-dispatched
physical acceptance in gate-only mode. Check actual status source, physical
test count and production package unchanged. Only then apply:

    python3 -m gway_remote.android_acceptance_ruleset --ruleset 24802372 --apply

This adds only Android acceptance and preserves strict CI and other protections.
If rollback is necessary, remove only that context under owner authority;
never remove CI or use merge bypass.

## Recovery

Missing/stale/failed runs, unavailable hardware, signature conflicts without
opt-in, failed tests and publication failures stop the process. New explicit
dispatch is required; no automatic unlock or unlimited retry. If main moves
during publication, retain the stale-main guard and leave issues open.
If an exact asset was published but verification/closure failed, independently
verify the published APK signature against the production signing identity and
its SHA256 and commit, then run the close helper from trusted main. Never
close an issue solely because of a successful merge.

## Temporary staged CRM publication hold (#718)

The merge preserves the existing publication suspension: the publisher accepts
only ordinary manual dispatch, with no expected_sha, until CRM acceptance.
The marker ANDROID_PUBLICATION_HOLD_718 blocks the coordinator's auto-merge
before any production publication. Gate-only physical acceptance remains
available. After #718 physical acceptance, restore the publisher's normal
condition (main, non-pull-request) and remove that marker together in a reviewed
PR. Do not use the ordinary manual release to bypass the CRM acceptance.

## Dispatch visibility contract

Dispatch creates the workflow exactly once, then checks the returned repository
run URL with the same credential. It returns the run ID only after a successful
read confirms the expected ID, repository, workflow path, event, main branch
and valid revision (the exact expected commit for release dispatch). Initial
HTTP 404 reads are retried at most eight times, within a 135-second visibility
budget, with individual reads limited to 15 seconds. Other errors fail closed.
An uncertain creation or visibility timeout requires reconciliation, never
another automatic dispatch. The completion waiter separately verifies identity
and terminal success. No permission or credential changes are required.
