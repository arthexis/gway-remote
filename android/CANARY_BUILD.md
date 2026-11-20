# Android: manual canary APKs

A canary APK allows on-device validation **before merging an Android PR**
without creating extra builds on routine pushes or backend merges.

## Start a run

Open **Actions → Android Canary APK (manual) → Run workflow**. Select
**main** as the workflow branch, and provide the open PR number plus its
exact **40-character HEAD SHA**. For the current modular Android UI:
PR **#644**, SHA **73ab5e2b8d8559b5f2a7bbbfda7b63480d1575a3** (recheck
the HEAD before clicking Run workflow).

The job validates that the PR exists, is still open, belongs to this
repository, and has exactly the supplied HEAD. It then checks out that
commit and builds **only** Gradle task `:app:assembleDebug` (no test suite,
emulator, or release signing).

The resulting GitHub Actions artifact is named
`android-canary-pr<PR>-<SHA12>`, retained for **14 days**. It includes:

- `gway-remote-canary.apk` — installable debug APK.
- `SHA256SUMS` — digest to check before installation.
- `PROVENANCE.txt` — PR, full commit SHA, run ID, overlay and package name.

## Isolation and provenance

Because existing Android PRs do not contain a build flavor, the workflow
applies a strictly checked, temporary overlay **during CI only**: it changes
the app ID to `com.arthexis.gwayremote.canary` and the launcher label to
**GWay Remote Canary**. The source SHA and overlay are disclosed in the
provenance; this is intentionally *source SHA + build-only overlay*, not an
untouched binary image of the repository.

The canary has separate app storage and debug signing, and **cannot
overwrite** production package `com.arthexis.gwayremote`. It is not a
production updater candidate and no APK is published to GitHub Releases.
An ephemeral debug signing key can change between runs, so Android may
require uninstalling only an older canary before installing another. Do not
remove or reset the production installation or production credentials.

Tests of basic navigation and layout can be performed without configuring
the production connection. The passkey and update paths depend on production
signing/app associations and should not be claimed as validated by the canary.
Avoid mutating backend operations during manual navigation checks.

## Build policy

The canary workflow is **workflow_dispatch only**, on demand. Existing
`.github/workflows/android.yml` already uses `android/**` path filters
for its routine PR tests and main-branch release builds; a backend-only
merge does not invoke those Android jobs. The canary workflow does not
change that policy or create a new regular CI job.

The workflow requires only repository read access. It does not access
release signing secrets, overwrite releases, trigger deployments, install
an APK onto a device, or start a second Gradle test matrix.
