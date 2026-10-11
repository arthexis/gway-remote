# Android companion — Chunk 4

Native Kotlin/Jetpack Compose client for the existing read-only GWay Remote API.

## Development

Requires Android SDK 35, Java 17, Gradle 8.10.2. From `android/` run `gradle :app:testDebugUnitTest :app:assembleDebug`. The CI workflow installs Gradle directly; no Gradle wrapper binary is checked in. Debug APK is uploaded as an Actions artifact for PRs and pushes to main.

The app requires a **trusted HTTPS endpoint** and an API bearer token. It does not accept plaintext HTTP or disable TLS certificate validation. Chunk 3 did not install a public HTTPS gateway; the APK cannot connect to a loopback-only node until a trusted route exists. The endpoint is stored in private app preferences; the token is encrypted with a per-install Android Keystore AES-GCM key. Backups are disabled. No tokens are included in source or APK.

Saved connection fields are hidden by default and can be reopened with the gear icon. The app currently exposes all zero-argument read-only commands advertised by the server; currently the API advertises only `probe-csms` and `status`. Expanding the server's allowlist is separate from the Android UI.\n\nThe app provides a connection test, server command discovery, and execution of read-only zero-argument operations. All network I/O runs off the UI thread. Commands are discovered from the server, not executed as shell commands.

## Release distribution

Tag `android-v0.1.0` (or a later `android-v*` tag) to trigger a **signed** release build and publish `gway-remote.apk` on GitHub Releases. Configure these repository Actions secrets **before tagging**:

- `GWAY_APK_KEYSTORE_BASE64`: base64-encoded release JKS file
- `GWAY_APK_STORE_PASSWORD`
- `GWAY_APK_KEY_ALIAS`
- `GWAY_APK_KEY_PASSWORD`

If any secret is missing, the release job fails rather than publishing an unsigned APK. Preserve the signing key securely; Android updates require the same signing identity. Do not put signing credentials in the repository. Download from `https://github.com/arthexis/gway-remote/releases`. A stable URL is available after the first release: `https://github.com/arthexis/gway-remote/releases/latest/download/gway-remote.apk`.

The current versionCode is 3 and versionName is 0.1.2; **increase both for subsequent releases**. No release is created merely by merging this PR.

## Limitations

This initial UI displays structured JSON responses and discovers read-only commands. It does not include push notifications, background polling, QR provisioning, charger control, or deployments. On-device validation and real HTTPS routing are pending.

## In-app updates

The app checks the latest stable GitHub Release on launch and from **gear → Check for updates**. Releases must include a signed `gway-remote.apk`, an asset `sha256:` digest supplied by GitHub, and a release-body line `Android-Version-Code: N` (the Android release workflow now writes this line). The app downloads only the fixed repository's HTTPS release APK, limits size to 100 MiB, verifies SHA-256, and hands the APK to Android's system installer using a private FileProvider URI. Android enforces the signing identity and asks the user to confirm installation. On first use, enable **Install unknown apps** for GWay Remote, then tap **Install downloaded update**. A previous APK installed with a different signing key cannot be upgraded in place.

The update mechanism requires a newly published signed release. PR artifacts and debug builds are not update candidates. Version codes must increase for every release; existing releases without metadata are not supported by the update checker.
