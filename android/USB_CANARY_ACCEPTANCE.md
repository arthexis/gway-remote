# Physical Android canary acceptance on gway-001

## Model

The existing manual GitHub Actions workflow in `.github/workflows/android-canary.yml` compiles two signed artifacts **from the same exact PR HEAD**: `gway-remote-canary.apk` and `gway-remote-canary-test.apk`. It also supplies `SHA256SUMS` and `PROVENANCE.txt`. The app ID is **`com.arthexis.gwayremote.canary`**, separate from production. Versions start with `0.0.1-canary.<workflow run number>-<SHA12>`.

The workflow is **manual-only**: creating or merging a normal backend change does not build a new Android APK. The field consumer only sees successful manual canary runs, restricted to the exact open PR allowed on this node. It checks that PR's latest HEAD, the official GitHub run and artifact name, the full provenance and hashes. An older or unrelated run is not eligible.

The field consumer needs `python3`, an authenticated GitHub CLI `gh` capable of **read-only** artifact download, and the ADB client already used by the local Android provider. **No Java, Gradle or Android SDK is required on gway-001.** If these dependencies are missing, provisioning is an explicit separate task; do not embed credentials in service files or command arguments.

## First acceptance

1. Prepare a fresh manual canary build for the current #644 HEAD and confirm **both** APKs and checksum/provenance in the artifact. The older run 44789265881 has only the application APK and cannot satisfy this two-APK contract.
2. Install the updated package on `gway-001` through the existing managed deployment process; do not run `node_exec` or general ADB through MCP as a substitute for the dedicated Android tools.
3. Confirm exactly one authorized **physical USB** Android. The device must be awake and explicitly unlocked; this runner never unlocks or supplies a PIN.
4. Dry-run provenance: `python3 -m gway_remote.android_canary_field --pr 644`. This checks the artifact **without installing**.
5. Controlled one-shot field run: `python3 -m gway_remote.android_canary_field --pr 644 --install --wake`. The program verifies provenance, installs only the canary app/test packages and runs an allowlisted set of hermetic Compose instrumented tests. It reports a sanitized summary and never writes raw screenshots/serials/test logs to GitHub.
6. Review the receipt at `~/.local/state/gway-remote/android-canary.json` and do a separate visual acceptance of the actual app's shell, drawer, Back and navigation. The component Compose tests **do not** constitute complete end-to-end acceptance of the installed UI.
7. If later canaries use different ephemeral debug certificates, an operator may explicitly enable `--allow-canary-reset`, which permits uninstall/reinstall **only** the isolated canary packages and only after a recognized signature/version-conflict error. This discards *canary-only* app data. Never use that option where the canary contains valuable data.

## Physical screen stability and receipt validation

On an authorized USB Android, a successful package install alone is **not** enough to
prove that Compose instrumented tests can run. A sleeping or dozing display may
cause `java.lang.IllegalStateException: No compose hierarchies found in the app`
even when the same APK subsequently passes every component test.

The local field runner rechecks the awake/unlocked state **after installation**
and again immediately before AndroidJUnitRunner. During instrumentation it
temporarily enables the Android global `stay_on_while_plugged_in` USB bit (2)
**only if USB power is confirmed**. It reads the previous value, restores that
same value (including absence), and verifies restoration before reporting
success. No permanent Android developer setting is required, and the runner
never unlocks a phone. Do not activate periodic polling if this restoration or
the lock-state check is unverified.

The physical regression for PR #661 was accepted on the authorized USB device
with a provenance-verified #644 canary from Actions run #44827589525:
**6/6 PASS immediately after reinstall** and **6/6 PASS on an independent
second instrumentation run**. These are hermetic component assertions, not
full interactive acceptance of the installed drawer, Back behavior or module
navigation. Keep #644 and issue #647 open until those visual behaviors are
independently verified; keep the unattended timer opt-in.

## Opt-in periodic polling

The user service and timer are templates in `deploy/systemd/user/`, and are **not enabled automatically**. After successful one-shot physical acceptance, install them in the installation user's systemd user directory, review the configured PR allowlist and `ExecStart`, create `~/.config/gway-remote/android-canary-enabled` intentionally, and enable/start the timer with `systemctl --user`.

The timer checks at most once approximately every 45 minutes. It **does not compile** APKs or trigger GitHub workflows. It only consumes an artifact already published by an explicitly dispatched successful GitHub workflow, and marks each attempted run once; failures are not automatically retried indefinitely. The service requires an authenticated GitHub CLI and an eligible unlocked/awake USB device. It may wake and restore a previously sleeping display, but never unlocks it.

Stop monitoring by removing `android-canary-enabled` and disabling the user timer. Do not activate this on Watchtower, charger servers, gway-002 or gway-005.

## Scope of test coverage

Current instrumented suite: `ModuleNavigationComposeTest`, `ModulePageComposeTest`, `AppearanceThemeTest`. These run Compose UI components on a real Android device with fake callbacks, asserting routing, home content, layout wrapping and theme behavior. They are not allowed to submit deployments, mutate Odoo, issue AgentOps tasks or control chargers. No production package is installed, uninstalled or force-stopped by the runner.

Record the exact PR, SHA, Actions run, package version, test count, and failure status against #647, without private screen content. #644 stays Draft until the independent physical visual acceptance passes.
