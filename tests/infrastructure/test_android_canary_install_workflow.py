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

    def test_physical_compose_is_opt_in_and_pinned_to_verified_artifact(self):
        text = WORKFLOW.read_text()
        self.assertIn("run_compose_tests:", text)
        self.assertIn("RUN_HERMETIC_TESTS", text)
        self.assertIn('default: "no"', text)
        self.assertIn('inputs.run_compose_tests ==', text)
        self.assertIn('CANARY_RESET: ${{ inputs.canary_reset }}', text)
        self.assertIn('GH_TOKEN: ${{ github.token }}', text)
        self.assertIn("gway_remote.android_canary_field", text)
        self.assertIn("--install --allow-canary-reset --wake", text)
        self.assertIn('r.get("source_sha") == os.environ["EXPECTED_SHA"]', text)
        self.assertIn('str(r.get("run_id")) == os.environ["ARTIFACT_RUN"]', text)
        self.assertIn('"baseline": 6', text)
        self.assertIn('"quotations": 5', text)
        self.assertIn('"opportunities": 2', text)
        self.assertLess(text.index("Install ONLY isolated canary"), text.index("Run pinned hermetic Compose tests"))

    def test_named_quotation_suite_is_explicit_and_receipt_bound(self):
        text = WORKFLOW.read_text()
        self.assertIn("compose_suite:", text)
        self.assertIn("default: baseline", text)
        self.assertIn("COMPOSE_SUITE: ${{ inputs.compose_suite }}", text)
        self.assertIn('case "$COMPOSE_SUITE" in baseline|quotations|opportunities)', text)
        self.assertIn('--suite "$COMPOSE_SUITE"', text)
        self.assertIn('r.get("suite") == os.environ["COMPOSE_SUITE"]', text)
        self.assertIn('"opportunities": 2', text)
        self.assertIn('no) RESULT=$(python3 -m gway_remote.android_canary_field --pr "$PR_NUMBER" --install --wake --expected-run "$ARTIFACT_RUN" --suite "$COMPOSE_SUITE")', text)
        self.assertIn('RESET_CANARY_ONLY) RESULT=$(python3 -m gway_remote.android_canary_field --pr "$PR_NUMBER" --install --allow-canary-reset --wake --expected-run "$ARTIFACT_RUN" --suite "$COMPOSE_SUITE")', text)

    def test_standalone_install_excludes_compose_and_feed(self):
        text = WORKFLOW.read_text()
        standalone = text.split("Install ONLY isolated canary", 1)[1].split("Run pinned hermetic Compose tests", 1)[0]
        self.assertIn("inputs.run_feed_tests == 'no' && inputs.run_compose_tests == 'no'", standalone)
        self.assertIn("gway_remote.android_canary_install", standalone)
        compose = text.split("Run pinned hermetic Compose tests", 1)[1].split("Upload sanitized physical acceptance receipt", 1)[0]
        self.assertIn("inputs.run_compose_tests == 'RUN_HERMETIC_TESTS'", compose)
        self.assertIn("gway_remote.android_canary_field", compose)
