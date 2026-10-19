"""Structural invariants for the unittest suite."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
GROUPS = ("codex", "core", "deployment", "infrastructure", "mobile", "simulator")


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

    def test_each_subsystem_has_discovered_tests(self):
        loader = unittest.TestLoader()
        for group in GROUPS:
            suite = loader.discover(str(TESTS / group), top_level_dir=str(ROOT))
            with self.subTest(group=group):
                self.assertGreater(suite.countTestCases(), 0)
                self.assertEqual(loader.errors, [])
