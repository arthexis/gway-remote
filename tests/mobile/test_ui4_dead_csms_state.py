"""Guard removal of obsolete legacy CSMS view state without losing new panels."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ACTIVITY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/MainActivity.kt"
PALETTE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt"


class DeadCsmsStateTests(unittest.TestCase):
    def test_obsolete_state_and_refresh_are_absent(self):
        activity = ACTIVITY.read_text()
        for marker in ("csmsExpanded", "csmsView", "csmsMenuOpen",
                       "csmsOutput", "csmsTruncated", "csmsHealthy",
                       "csmsReason", "refreshCsms"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, activity)

    def test_new_panel_retains_health_and_inspection(self):
        palette = PALETTE.read_text()
        self.assertIn("CsmsHealthPanel(panel.output)", palette)
        self.assertIn("CsmsInspectionPanel(panel.output)", palette)
        self.assertIn('"Output truncated to 64 KB"', palette)


if __name__ == "__main__":
    unittest.main()
