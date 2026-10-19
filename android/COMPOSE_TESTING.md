# Android Compose UI tests

Instrumented tests run production Compose components with fake callbacks, without connecting to Gway-001 or a backend. The normal pull-request checks continue to run Android JVM tests only.

## GitHub Actions

From **Actions → Android Compose UI Tests → Run workflow**, select the branch and one profile:

| Profile | Emulator configuration |
| --- | --- |
| `phone` | Default Pixel 6 (baseline) |
| `narrow` | 720 × 1560 px, 320 dpi (360 dp width) |
| `tablet` | 1600 × 2400 px, 320 dpi (800 dp width) |
| `large-text` | Default Pixel 6, font scale 1.5 |

The Android 35 x86_64 emulator uses KVM on the GitHub-hosted Ubuntu runner. Each run tests **one profile**; no automatic matrix and no emulator run on routine PRs.

The runner invokes `android/scripts/run-compose-ui-tests.sh`, preserving Android instrumented XML/results and emulator logcat, device geometry, and font scale. A failure also records a screenshot of the emulator's current screen. All evidence is uploaded under the `compose-ui-<profile>-<run id>` artifact, including on failures. The captured screenshot is diagnostic, not a pixel-perfect golden baseline.

Initial acceptance: manually run the workflow on the PR branch (once GitHub exposes the workflow on the default branch), starting with `phone`, then `narrow`, `tablet`, and `large-text`. Repeat the baseline to check reproducibility before enabling any automatic trigger. **No emulator acceptance should be claimed until real Actions runs finish successfully.**

## Local execution

Start an API 35 emulator, then from repository root:

```sh
bash android/scripts/run-compose-ui-tests.sh phone
```

The script writes diagnostics to `android/build/compose-ui-diagnostics`, and automatically restores screen and font overrides afterward.

## Automation policy

Keep `workflow_dispatch` only until the baseline is stable across repeated emulator runs. A later focused change may add a path-filtered `pull_request` trigger for Compose UI files and `androidTest`; it should not run for Python-only changes or trigger multiple emulators per PR.
