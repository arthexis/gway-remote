"""UI-4h simulator panel presentation regression checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PALETTE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt"
REGISTRY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationRegistry.kt"


class SimulatorPanelParityTests(unittest.TestCase):
    def test_results_are_presented_in_dedicated_panel(self):
        text = PALETTE.read_text()
        for marker in (
            'panel.id == "simulator-results"',
            'panel.id == "simulator-status"',
            "SimulatorActivitySummary.parse(log, truncated)",
            'result.optString("outcome", "unknown")',
            'result.optBoolean("truncated", false)',
            '"Show raw output"',
            '"Hide raw output"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_reads_stay_safe_and_refreshable(self):
        registry = REGISTRY.read_text()
        for command in ("simulator-status", "simulator-results"):
            with self.subTest(command=command):
                start = registry.index('OperationSpec("' + command + '"')
                self.assertIn('ExecutionPolicy.AUTO_READ', registry[start:start + 220])
        self.assertIn('onRefresh(panel.id)', PALETTE.read_text())


if __name__ == "__main__":
    unittest.main()
