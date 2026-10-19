#!/usr/bin/env bash
# Runs inside android-emulator-runner, while adb still has a live emulator.
set -euo pipefail
profile="${1:-phone}"
diagnostics="android/build/compose-ui-diagnostics"
mkdir -p "$diagnostics"

case "$profile" in
  phone) ;;
  narrow)
    adb shell wm size 720x1560
    adb shell wm density 320
    ;;
  tablet)
    adb shell wm size 1600x2400
    adb shell wm density 320
    ;;
  large-text)
    adb shell settings put system font_scale 1.5
    ;;
  *) echo "Unsupported UI profile: $profile" >&2; exit 2 ;;
esac

collect_evidence() {
  status=$?
  trap - EXIT
  adb logcat -d -v threadtime > "$diagnostics/logcat.txt" 2>/dev/null || true
  adb shell wm size > "$diagnostics/screen-size.txt" 2>/dev/null || true
  adb shell wm density > "$diagnostics/screen-density.txt" 2>/dev/null || true
  adb shell settings get system font_scale > "$diagnostics/font-scale.txt" 2>/dev/null || true
  if (( status != 0 )); then
    adb exec-out screencap -p > "$diagnostics/failure-screen.png" 2>/dev/null || true
  fi
  adb shell wm size reset >/dev/null 2>&1 || true
  adb shell wm density reset >/dev/null 2>&1 || true
  adb shell settings put system font_scale 1.0 >/dev/null 2>&1 || true
  exit "$status"
}
trap collect_evidence EXIT
cd android
bash ./gradlew connectedDebugAndroidTest --stacktrace
