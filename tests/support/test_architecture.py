"""Structural invariants for the unittest suite."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
GROUPS = ("codex", "core", "deployment", "infrastructure", "mobile")


class TestArchitecture(unittest.TestCase):
    def test_no_pytest_style_functions_hidden_from_unittest(self):
        for group in GROUPS:
            for path in (TESTS / group).glob("test_*.py"):
                module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                functions = [node.name for node in module.body
                             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and node.name.startswith("test_")]
                with self.subTest(path=str(path.relative_to(ROOT))):
                    self.assertEqual(functions, [], "Top-level test functions are not run by unittest")

    def test_simulator_subsystem_has_been_removed(self):
        # Ownership of simulator behavior belongs to arthexis/ocpp-simulator.
        self.assertFalse((ROOT / "tests/simulator").exists())
        for name in ("simulator_runner.py", "simulator_network.py",
                     "simulator_exit_monitor.py"):
            with self.subTest(module=name):
                self.assertFalse((ROOT / "gway_remote" / name).exists())
        self.assertNotIn("simulator", GROUPS)

    def test_android_simulator_components_are_absent(self):
        android = ROOT / "android/app/src"
        retired = (
            "main/java/com/arthexis/gwayremote/SimulatorControls.kt",
            "main/java/com/arthexis/gwayremote/SimulatorActivitySummary.kt",
            "main/java/com/arthexis/gwayremote/panels/SimulatorUnifiedPanel.kt",
            "test/java/com/arthexis/gwayremote/SimulatorPanelMigrationTest.kt",
            "test/java/com/arthexis/gwayremote/SimulatorPeerSelectionTest.kt",
        )
        for path in retired:
            with self.subTest(path=path):
                self.assertFalse((android / path).exists())

    def test_each_subsystem_has_discovered_tests(self):
        loader = unittest.TestLoader()
        for group in GROUPS:
            suite = loader.discover(str(TESTS / group), top_level_dir=str(ROOT))
            with self.subTest(group=group):
                self.assertGreater(suite.countTestCases(), 0)
                self.assertEqual(loader.errors, [])
