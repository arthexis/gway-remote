"""UI-4j CSMS panel migration checks using unittest discovery."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PALETTE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt"
ACTIVITY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/MainActivity.kt"


class CsmsPanelParityTests(unittest.TestCase):
    def test_health_and_inspection_presentations(self):
        source = PALETTE.read_text()
        for marker in ('CsmsHealthPanel(panel.output)', 'CsmsInspectionPanel(panel.output)',
                       '"Health unknown"', '"Needs attention"', '"No diagnostic details"',
                       '"Output truncated to 64 KB"', '"No inspection output returned"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

    def test_legacy_csms_and_apk_controls_remain(self):
        source = ACTIVITY.read_text()
        for marker in ('Text("CSMS"', 'Text("OCPP Simulator"', 'Update app',
                       '"probe-csms"', '"csms-view"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
