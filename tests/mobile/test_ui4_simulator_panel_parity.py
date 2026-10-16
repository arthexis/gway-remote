"""UI-4h simulator panel presentation regression checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PALETTE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt"
REGISTRY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationRegistry.kt"
CONTENT_REGISTRY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/registry/PanelContentRegistry.kt"


class SimulatorPanelParityTests(unittest.TestCase):
    def test_results_are_presented_in_dedicated_panel(self):
        text = PALETTE.read_text()
        mappings = CONTENT_REGISTRY.read_text()
        self.assertIn('"simulator-results" to PanelContentKind.SIMULATOR_RESULTS', mappings)
        self.assertIn('"simulator-status" to PanelContentKind.SIMULATOR_STATUS', mappings)
        self.assertIn("PanelContentKind.SIMULATOR_RESULTS -> SimulatorResultsPanel(panel.output)", text)
        self.assertIn("PanelContentKind.SIMULATOR_STATUS -> SimulatorStatusPanel(panel.output)", text)
        for marker in (
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
