"""UI-4 simulator status synchronization regressions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ACTIVITY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/MainActivity.kt"


class SimulatorStatusSyncTests(unittest.TestCase):
    def test_read_refresh_updates_control_status_without_stale_results(self):
        content = ACTIVITY.read_text()
        self.assertIn('id == "simulator-status" && stillCurrent', content)
        self.assertIn('it.id == id && it.loading && it.revision == revision', content)
        self.assertIn('simulatorStatus = if (detail == null) "unknown"', content)
        self.assertIn('panelState = panelState.complete(id, revision, response.toString(2))', content)

    def test_legacy_simulator_controls_are_retained_until_parity(self):
        content = ACTIVITY.read_text()
        self.assertIn('Text("OCPP Simulator"', content)
        self.assertIn('SimulatorControls(', content)


if __name__ == "__main__":
    unittest.main()
