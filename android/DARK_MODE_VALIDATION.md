# D4 — Android appearance validation

D1–D3 add a Compose Material 3 theme, native window bar styling, and a persisted appearance preference. D4 acceptance requires both automated and hands-on testing.

## Automated checks

1. Confirm **Android APK** and **Python checks** are green on PR #186.
2. The JVM suite includes `AppearanceModeTest` for System/Light/Dark fallback and overrides.
3. The instrumented `AppearanceThemeTest` changes the theme in a running Compose composition and checks that the orange update indicator remains present in both themes.
4. Run **Actions → Android Compose UI Tests → Run workflow** on the PR branch, with the `phone` profile; repeat with `large-text` and `narrow` if available. This workflow is manually triggered and does not execute as part of normal PR CI. A green JVM build does **not** replace emulator testing.

## Manual acceptance on a real Android device

1. Install the APK built from PR #186. Open **Settings (gear) → Appearance**.
2. Choose **System**. Set Android **Settings → Display → Dark theme** to off, then on. Gway Remote should switch immediately, including its status/navigation bar icon contrast, without restarting or losing open panel state.
3. Choose **Light** and enable Android dark mode. The application should remain light.
4. Choose **Dark** and disable Android dark mode. The application should remain dark.
5. Force-stop and reopen the app. The chosen appearance should persist.
6. Return to **System** and reopen: it must follow Android again. With Android automatic dark-theme scheduling enabled, verify the transition at the next scheduled change.
7. Check the **App update** orange dot (when an update is actually available), two-column palette, System, CSMS, Notifications, Settings text fields and error/result cards in both themes. Check contrast and readability with a large font setting.
8. In particular verify the startup/splash background, system bars, keyboard and edge-to-edge inset regions; report any remaining flash of the wrong theme.

## Known boundaries

The orange indicator uses a fixed amber `#FF9800` for continuity; its visibility is covered by UI instrumentation, but subjective contrast still needs a real-device check. No dynamic wallpaper color scheme is enabled.

If an emulator job fails, download its `compose-ui-*` artifact (instrumented XML, logcat, screen metadata and failure screenshot). Attach the relevant logs to PR #186.
