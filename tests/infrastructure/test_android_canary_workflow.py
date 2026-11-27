"""Guard manual Android canary artifact isolation and routine build cost."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
CANARY = ROOT / ".github/workflows/android-canary.yml"
ANDROID = ROOT / ".github/workflows/android.yml"
GRADLE = ROOT / "android/app/build.gradle.kts"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"


class CanaryWorkflowTests(unittest.TestCase):
    def test_only_manually_requested_with_read_permissions(self):
        content = CANARY.read_text()
        self.assertIn("on:\n  workflow_dispatch:\n", content)
        self.assertNotIn("\n  push:", content)
        self.assertNotIn("\n  pull_request:", content)
        self.assertIn("contents: read", content)
        self.assertIn("pull-requests: read", content)
        self.assertIn("github.ref == 'refs/heads/main'", content)
        for unsafe in ("secrets.", "gh release create", "assembleRelease",
                       "testDebugUnitTest", "android-emulator-runner", "deployment"):
            self.assertNotIn(unsafe, content)

    def test_build_proves_exact_open_or_merged_pr_and_isolates_package(self):
        content = CANARY.read_text()
        for required in ("EXPECTED_SHA", "gh api", ".head.sha", ".head.repo.full_name",
                         "ref: ${{ steps.source.outputs.sha }}",
                         "git rev-parse HEAD", "com.arthexis.gwayremote.canary",
                         'android:label="GWay Remote Canary"',
                         "ephemeral Android debug certificate"):
            self.assertIn(required, content)
        self.assertIn("PR_MERGED=$(jq -r .merged", content)
        self.assertIn('"$PR_MERGED" == "true"', content)
        self.assertIn('PR_STATE" == "open"', content)
        self.assertIn('PR_STATE" == "closed"', content)
        self.assertIn('Received status code 429', content)
        self.assertIn('for attempt in 1 2 3', content)
        self.assertIn('if ! grep -Eq', content)
        self.assertIn('applicationId = "com.arthexis.gwayremote"', GRADLE.read_text())
        self.assertIn('android:label="GWay Remote"', MANIFEST.read_text())

    def test_artifact_is_retrievable_and_checksum_verified(self):
        content = CANARY.read_text()
        for required in ("gradle :app:assembleDebug :app:assembleDebugAndroidTest --no-daemon",
                         "apksigner", "aapt", "PROVENANCE.txt", "SHA256SUMS",
                         "upload-artifact@v4", "retention-days: 14",
                         "if-no-files-found: error"):
            self.assertIn(required, content)

    def test_existing_android_workflow_is_path_filtered(self):
        content = ANDROID.read_text()
        self.assertIn("paths: ['android/**', '.github/workflows/android.yml', '.github/workflows/android-compose-ui.yml']", content)
        self.assertIn("push:\n    branches: [main]\n    paths: ['android/**']", content)

    def test_public_certificate_evidence_and_matching_test_signer(self):
        content = CANARY.read_text()
        self.assertIn("--print-certs", content)
        self.assertIn("Signer #1 certificate SHA-256 digest", content)
        self.assertIn('[[ "$APK_CERT" == "$TEST_CERT" ]]', content)
        self.assertIn("Canary certificate SHA256:", content)
        self.assertIn("Canary test certificate SHA256:", content)

    def test_no_separate_persistent_canary_signer(self):
        self.assertFalse((ROOT / ".github/workflows/android-canary-signing.yml").exists())
        self.assertNotIn("secrets.", CANARY.read_text())


if __name__ == "__main__":
    unittest.main()
