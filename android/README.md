# Android companion — Chunk 4

Native Kotlin/Jetpack Compose client for the existing read-only GWay Remote API.

## Development

Requires Android SDK 35, Java 17, Gradle 8.10.2. From `android/` run `gradle :app:testDebugUnitTest :app:assembleDebug`. The CI workflow installs Gradle directly; no Gradle wrapper binary is checked in. Debug APK is uploaded as an Actions artifact for PRs and pushes to main.

The app requires a **trusted HTTPS endpoint** and an API bearer token. It does not accept plaintext HTTP or disable TLS certificate validation. Chunk 3 did not install a public HTTPS gateway; the APK cannot connect to a loopback-only node until a trusted route exists. The endpoint is stored in private app preferences; the token is encrypted with a per-install Android Keystore AES-GCM key. Backups are disabled. No tokens are included in source or APK.

Saved connection fields are hidden by default and can be reopened with the gear icon. The app currently exposes all zero-argument read-only commands advertised by the server; currently the API advertises only `probe-csms` and `status`. Expanding the server's allowlist is separate from the Android UI.\n\nThe app provides a connection test, server command discovery, and execution of read-only zero-argument operations. All network I/O runs off the UI thread. Commands are discovered from the server, not executed as shell commands.

## Release distribution

Every push to `main` builds and publishes a **signed** release APK with an automatically increasing version and unique `android-v0.2.<run number>` tag, including backend-only changes. If a newer `main` commit arrives before publication, the stale run refuses to publish and the newer run takes over. Configure these repository Actions secrets **before merging to `main`**:

- `GWAY_APK_KEYSTORE_BASE64`: base64-encoded release JKS file
- `GWAY_APK_STORE_PASSWORD`
- `GWAY_APK_KEY_ALIAS`
- `GWAY_APK_KEY_PASSWORD`

If any secret is missing, the release job fails rather than publishing an unsigned APK. Preserve the signing key securely; Android updates require the same signing identity. Do not put signing credentials in the repository. Download from `https://github.com/arthexis/gway-remote/releases`. A stable URL is available after the first release: `https://github.com/arthexis/gway-remote/releases/latest/download/gway-remote.apk`.

Local builds default to versionCode 4 and versionName 0.1.3; main CI overrides these with the workflow run number. Signed APK publishing requires configured secrets.

## Limitations

This initial UI displays structured JSON responses and discovers read-only commands. It does not include push notifications, background polling, QR provisioning, charger control, or deployments. On-device validation and real HTTPS routing are pending.

## In-app updates

The app checks the latest stable GitHub Release on launch and from **gear → Check for updates**. Releases must include a signed `gway-remote.apk`, an asset `sha256:` digest supplied by GitHub, and a release-body line `Android-Version-Code: N` (the Android release workflow now writes this line). The app downloads only the fixed repository's HTTPS release APK, limits size to 100 MiB, verifies SHA-256, and hands the APK to Android's system installer using a private FileProvider URI. Android enforces the signing identity and asks the user to confirm installation. On first use, enable **Install unknown apps** for GWay Remote, then tap **Install downloaded update**. A previous APK installed with a different signing key cannot be upgraded in place.

The update mechanism requires a newly published signed release. PR artifacts and debug builds are not update candidates. Version codes must increase for every release; existing releases without metadata are not supported by the update checker.

## Manual LCD and sound controls

The app provides two separate printable ASCII input fields of at most 16 characters each. The server independently enforces both limits and publishes a 30-second event through the existing `gway-lcd-sound` LCD lockfile runner; normal rotation resumes afterward. The mobile API process must run as the same user as the LCD runner and have write access to `~/.local/state/lcd-lockfiles`. The sound selector offers the existing `ok`, `notice`, `attention`, `warning`, `error`, `busy`, and `critical` sounds via the installed `/usr/local/bin/sound` utility. There is no arbitrary shell execution.

## Consolidated release on merge

Merging any PR to main runs Android tests and attempts to publish a newly versioned signed release APK. The signing secrets must be configured, and an existing release with the same version is never overwritten. The updater discovers the signed release using GitHub's release metadata and SHA-256 asset digest. No release is published from PR builds; device testing remains necessary.

## Composable command surface — UI-1 foundation

`OperationRegistry.kt` defines stable IDs, labels, icon identifiers, search keywords, optional backend command bindings and three execution policies: `AUTO_READ`, `EXPLICIT_INPUT` and `CONFIRM`. Only safe, parameterless read operations can execute when a future panel opens. Inputs require explicit Run and potentially disruptive operations require confirmation. UI-1 does not replace the current navigation, change backend contracts or expose Agent Ops issue execution. UI-2 will consume the registry through independent panel state.

## UI-2 panel manager

`OperationPanels.kt` defines immutable, independent panel state (`inputs`, `loading`, `output`, `error`), duplicate-free opening, newest-first placement, close/reorder operations, and palette filtering of unopened operations. Monotonic request revisions reject out-of-order responses even after a panel closes and reopens. Restoring panel IDs never runs commands. `PanelExecution.canRun` enforces UI-1 auto-read, explicit-input, and confirmation policies at the controller boundary. This is intentionally a pure model; UI-3 will connect it to the Compose screen, preserving all current commands until migration parity.

## UI-3 palette rollout

The Android screen now shows independently open, reorderable bordered operation panels above the legacy controls, followed by a compact searchable palette of unopened operations. Opening a safe read-only operation fetches it once; Refresh explicitly fetches again. Closing/reopening rejects earlier asynchronous results via UI-2 request IDs. Parameterized and mutating operations remain in the existing controls until UI-4 moves their inputs and execution with parity tests; opening their new panels **does not** execute them. The existing updater, settings, refresh, CSMS, simulator, LCD, sound and benchmark controls remain reachable during this bridge phase.
