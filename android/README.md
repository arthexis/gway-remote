# Android companion — Chunk 4

Native Kotlin/Jetpack Compose client for the existing read-only GWay Remote API.

## Development

Requires Android SDK 35, Java 17, Gradle 8.10.2. From `android/` run `gradle :app:testDebugUnitTest :app:assembleDebug`. The CI workflow installs Gradle directly; no Gradle wrapper binary is checked in. Debug APK is uploaded as an Actions artifact for PRs and pushes to main.

The app requires a **trusted HTTPS endpoint** and an API bearer token. It does not accept plaintext HTTP or disable TLS certificate validation. Chunk 3 did not install a public HTTPS gateway; the APK cannot connect to a loopback-only node until a trusted route exists. The endpoint is stored in private app preferences; the token is encrypted with a per-install Android Keystore AES-GCM key. Backups are disabled. No tokens are included in source or APK.

The app provides a connection test, server command discovery, and execution of read-only zero-argument operations. All network I/O runs off the UI thread. Commands are discovered from the server, not executed as shell commands.

## Release distribution

Tag `android-v0.1.0` (or a later `android-v*` tag) to trigger a **signed** release build and publish `gway-remote.apk` on GitHub Releases. Configure these repository Actions secrets **before tagging**:

- `GWAY_APK_KEYSTORE_BASE64`: base64-encoded release JKS file
- `GWAY_APK_STORE_PASSWORD`
- `GWAY_APK_KEY_ALIAS`
- `GWAY_APK_KEY_PASSWORD`

If any secret is missing, the release job fails rather than publishing an unsigned APK. Preserve the signing key securely; Android updates require the same signing identity. Do not put signing credentials in the repository. Download from `https://github.com/arthexis/gway-remote/releases`. A stable URL is available after the first release: `https://github.com/arthexis/gway-remote/releases/latest/download/gway-remote.apk`.

The current versionCode is 1 and versionName is 0.1.0; **increase both for subsequent releases**. No release is created merely by merging this PR.

## Limitations

This initial UI displays structured JSON responses and discovers read-only commands. It does not include push notifications, background polling, QR provisioning, charger control, deployments, or in-app updates. On-device validation and real HTTPS routing are pending.
