"""UI-4e migration guard: remove duplicate writes, preserve unfinished controls."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ACTIVITY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/MainActivity.kt"
PALETTE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt"


class LegacyParityTests(unittest.TestCase):
    def test_lcd_and_sound_are_only_rendered_in_panels(self):
        activity = ACTIVITY.read_text()
        palette = PALETTE.read_text()
        self.assertNotIn('Text("Write operations"', activity)
        self.assertNotIn('expandedWriteOperation == "lcd-message"', activity)
        self.assertNotIn('expandedWriteOperation == "sound-play"', activity)
        for operation in ('panel.id == "lcd"', 'panel.id == "sound"'):
            self.assertIn(operation, palette)
        self.assertIn('"lcd-message"', activity)
        self.assertIn('"sound-play"', activity)

    def test_unmigrated_controls_stay_available(self):
        activity = ACTIVITY.read_text()
        for marker in ('Text("Read operations"', 'Text("CSMS"',
                       'Text("OCPP Simulator"', 'SimulatorControls(',
                       'Text("Response"', 'Update app'):
            self.assertIn(marker, activity)


if __name__ == "__main__":
    unittest.main()
