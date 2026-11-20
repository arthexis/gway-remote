"""Canary pair packaging and opt-in timer safety checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/android-canary.yml"
SERVICE = ROOT / "deploy/systemd/user/gway-remote-android-canary.service"
TIMER = ROOT / "deploy/systemd/user/gway-remote-android-canary.timer"


class AndroidCanaryPairTests(unittest.TestCase):
    def test_paired_apks_share_one_source_sha(self):
        data = WORKFLOW.read_text()
        for item in (
            "ref: ${{ steps.source.outputs.sha }}",
            "gradle :app:assembleDebug :app:assembleDebugAndroidTest --no-daemon",
            "gway-remote-canary-test.apk", "SHA256SUMS", "PROVENANCE.txt",
            "com.arthexis.gwayremote.canary.test",
            "targetPackage='com.arthexis.gwayremote.canary'",
            "0.0.1-canary.$GITHUB_RUN_NUMBER",
            "retention-days: 14",
        ):
            self.assertIn(item, data)
        self.assertIn("workflow_dispatch:", data)
        self.assertNotIn("\n  push:", data)
        self.assertNotIn("\n  pull_request:", data)
        self.assertNotIn("assembleRelease", data)
        self.assertNotIn("secrets.", data)

    def test_field_polling_is_opt_in_and_node_specific(self):
        data = SERVICE.read_text()
        timer = TIMER.read_text()
        self.assertIn("ConditionPathExists=%h/.config/gway-remote/android-canary-enabled", data)
        self.assertIn("--pr 644 --install", data)
        self.assertIn("--allow-canary-reset", data)
        self.assertIn("NoNewPrivileges=true", data)
        self.assertIn("OnUnitInactiveSec=45min", timer)
        self.assertNotIn("WantedBy=", data)
        self.assertNotIn("gh release", data)
        self.assertNotIn("systemctl restart", data)


if __name__ == "__main__":
    unittest.main()
