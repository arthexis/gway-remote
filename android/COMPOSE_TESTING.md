# Android Compose UI tests

Instrumented tests run production Compose components with fake callbacks, without connecting to Gway-001 or a backend. The normal pull-request checks continue to run Android JVM tests only.

## GitHub Actions

The workflow runs automatically on pull requests and pushes to `main` that change `android/**` or this workflow. Manual dispatch also runs the complete four-profile matrix:

| Profile | Emulator configuration |
| --- | --- |
| `phone` | Default Pixel 6 (baseline) |
| `narrow` | 720 × 1560 px, 320 dpi (360 dp width) |
| `tablet` | 1600 × 2400 px, 320 dpi (800 dp width) |
| `large-text` | Default Pixel 6, font scale 1.5 |

The Android 35 x86_64 emulator uses KVM on the GitHub-hosted Ubuntu runner. Each qualifying run tests **all four profiles** in parallel; Python-only changes do not trigger the emulator workflow.

The runner invokes `android/scripts/run-compose-ui-tests.sh`, preserving Android instrumented XML/results and emulator logcat, device geometry, and font scale. A failure also records a screenshot of the emulator's current screen. All evidence is uploaded under the `compose-ui-<profile>-<run id>` artifact, including on failures. The captured screenshot is diagnostic, not a pixel-perfect golden baseline.

Initial acceptance: validate the four-profile matrix in the PR and repeat a run to check reproducibility. Do not claim emulator acceptance until real Actions runs finish successfully.

## Local execution

Start an API 35 emulator, then from repository root:

```sh
bash android/scripts/run-compose-ui-tests.sh phone
```

The script writes diagnostics to `android/build/compose-ui-diagnostics`, and automatically restores screen and font overrides afterward.

## Automation policy

The workflow uses path-filtered `pull_request` and `push` triggers for Android changes, plus manual `workflow_dispatch`. The existing Android APK workflow remains separate. Avoid requiring this path-filtered workflow as a branch protection check without an always-running gate, because skipped workflows can leave required checks pending.
