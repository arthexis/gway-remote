"""Installation of canary is explicit, one-device and production-safe."""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/android-canary-install.yml"
INSTALLER = Path(__file__).resolve().parents[2] / "gway_remote/android_canary_install.py"

class CanaryInstallWorkflowTests(unittest.TestCase):
    def test_on_demand_only_authorized_runner(self):
        text = WORKFLOW.read_text()
        self.assertIn("on:\n  workflow_dispatch:", text)
        self.assertNotIn("\n  pull_request:", text)
        self.assertNotIn("\n  push:", text)
        self.assertIn("github.actor == 'arthexis'", text)
        self.assertIn("refs/heads/main", text)
        self.assertIn("self-hosted, Linux, ARM64, gway-001", text)
        self.assertIn("actions: read", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("sudo ", text)
        self.assertNotIn("adb tcpip", text)
        self.assertNotIn("adb connect", text)
        self.assertNotIn("uninstall", text)
        self.assertNotIn("shell am start", text)

    def test_provenance_before_install(self):
        text = WORKFLOW.read_text()
        for item in ('p["head"]["sha"]', 'p["head"]["repo"]["full_name"]', "actions/runs/",
                     'r["conclusion"]', 'r["path"]', "SHA256SUMS", "sha256sum --check",
                     "PROVENANCE.txt", "com.arthexis.gwayremote.canary",
                     "Canary-Overlay: package-and-label-v1",
                     "Install ONLY isolated canary"):
            self.assertIn(item, text)
        self.assertIn("expected_sha:", text)
        self.assertIn("apk_sha256:", text)
        self.assertIn("artifact_run_id:", text)
        self.assertIn("python3 -c", text)
        self.assertNotIn("jq -r", text)
        self.assertIn("gway_remote.android_canary_install", text)
        self.assertIn("RESET_CANARY_ONLY", text)
        self.assertIn('default: "no"', text)
        self.assertIn("--reset-canary", text)

        installer = INSTALLER.read_text()
        self.assertIn('"devices", "-l"', installer)
        self.assertIn('item.startswith("usb:")', installer)
        self.assertIn('serial.startswith("emulator-")', installer)
        self.assertIn('"install", "-r"', installer)
        self.assertIn('SIGNATURE_CONFLICT', installer)
        self.assertIn('adb("uninstall", CANARY', installer)
        self.assertIn('if package_path(PRODUCTION) != before:', installer)
        self.assertNotIn('adb("uninstall", PRODUCTION', installer)
