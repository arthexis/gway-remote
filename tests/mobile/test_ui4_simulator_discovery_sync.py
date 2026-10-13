"""Simulator discovery panel parity regression tests."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ACTIVITY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/MainActivity.kt"
PALETTE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt"


class DiscoverySynchronizationTests(unittest.TestCase):
    def test_discovery_requires_explicit_action_and_valid_port(self):
        activity = ACTIVITY.read_text()
        palette = PALETTE.read_text()
        self.assertIn('id == "simulator-discover"', activity)
        self.assertIn('port !in 1..65535', activity)
        self.assertIn('Text("Discover / check target")', palette)

    def test_discovery_results_live_in_panel_state_only(self):
        activity = ACTIVITY.read_text()
        palette = PALETTE.read_text()
        self.assertNotIn('simulatorPeers =', activity)
        self.assertNotIn('simulatorDiscovery =', activity)
        self.assertIn('panelState = panelState.complete(id, revision, response.toString(2))', activity)
        self.assertIn('val discovered = remember(panel.output)', palette)

    def test_selecting_peer_does_not_start_simulator(self):
        palette = PALETTE.read_text()
        activity = ACTIVITY.read_text()
        self.assertIn('onSelectSimulatorPeer(peer, panel.inputs["port"] ?: "9000")', palette)
        self.assertIn('onSelectSimulatorPeer = { host, port ->', activity)
        self.assertIn('Target selection only updates parameters', activity)


if __name__ == "__main__":
    unittest.main()
