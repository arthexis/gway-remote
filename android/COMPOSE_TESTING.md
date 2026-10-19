# Android Compose UI tests

Instrumented tests live in `android/app/src/androidTest/` and render production Compose components using fake callbacks (no Gway-001 credentials or external API calls).

Use GitHub Actions **Android Compose UI Tests** → **Run workflow** → select the PR branch. The workflow is deliberately manual and does not trigger for every pull request. It boots an API 35 x86_64 emulator with KVM on a Linux GitHub-hosted runner, invokes `connectedDebugAndroidTest`, and uploads instrumented test reports even when the job fails.

For local execution, start an API 35 emulator, then run:

```sh
cd android
./gradlew connectedDebugAndroidTest
```

The tests cover palette target geometry, CSMS inspection selection, Tasks history/detail display, and read-only Simulator tab routing. Pixel-perfect screenshot baselines are intentionally out of scope. JVM tests remain in the normal Android APK PR checks.
