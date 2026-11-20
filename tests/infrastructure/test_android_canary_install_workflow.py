"""Installation of canary is explicit, one-device and production-safe."""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/android-canary-install.yml"

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
        for item in (".head.sha", ".head.repo.full_name", "actions/runs/",
                     ".conclusion", ".path", "SHA256SUMS", "sha256sum --check",
                     "PROVENANCE.txt", "com.arthexis.gwayremote.canary",
                     "Canary-Overlay: package-and-label-v1",
                     "Install ONLY isolated canary"):
            self.assertIn(item, text)
        self.assertIn("expected_sha:", text)
        self.assertIn("apk_sha256:", text)
        self.assertIn("artifact_run_id:", text)
        self.assertIn("Expected exactly one USB device", text)
        self.assertIn("install -r", text)
        self.assertIn("PRODUCTION_BEFORE", text)
        self.assertIn("PRODUCTION_AFTER", text)
