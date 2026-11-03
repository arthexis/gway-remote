"""Simulator execution belongs to ocpp-simulator, not GWay Remote."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class NoSimulatorIntegrationTests(unittest.TestCase):
    def test_no_simulator_execution_module_or_ui(self):
        removed = [
            "gway_remote/simulator_runner.py",
            "gway_remote/simulator_network.py",
            "gway_remote/simulator_exit_monitor.py",
            "android/app/src/main/java/com/arthexis/gwayremote/SimulatorControls.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/SimulatorActivitySummary.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/panels/SimulatorUnifiedPanel.kt",
            "tests/simulator/test_simulator_hardening.py",
            "tests/simulator/test_simulator_network.py",
            "tests/simulator/test_simulator_outcomes.py",
            "tests/simulator/test_simulator_runner.py",
        ]
        for name in removed:
            with self.subTest(path=name):
                self.assertFalse((ROOT / name).exists())

    def test_no_simulator_command_or_deployment_wiring(self):
        paths = [
            "gway_remote/mobile.py",
            "gway_remote/__main__.py",
            "gway_remote/reconcile.py",
            "gway_remote/probe_registry.py",
            "gway_remote/best_effort.py",
            ".github/workflows/ci.yml",
            ".github/workflows/remote.yml",
            ".github/workflows/appliance-deploy.yml",
            "android/app/src/main/java/com/arthexis/gwayremote/MainActivity.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/OperationRegistry.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/OperationViewModel.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/RefreshRegistry.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/DeploymentsPanel.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/panels/OperationPanelHost.kt",
            "android/app/src/main/java/com/arthexis/gwayremote/registry/PanelContentRegistry.kt",
        ]
        for name in paths:
            with self.subTest(path=name):
                contents = (ROOT / name).read_text(encoding="utf-8").lower()
                self.assertNotIn("simulator", contents)


if __name__ == "__main__":
    unittest.main()
