"""Regression tests for the copy-paste Watchtower bootstrap command."""
import ast
import pathlib
import unittest


class RegisterCommandOutputTests(unittest.TestCase):
    def test_register_prints_complete_shell_command(self):
        source = pathlib.Path(__file__).resolve().parents[1] / "gway_remote" / "__main__.py"
        tree = ast.parse(source.read_text())
        register_outputs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "print" and node.args
            and isinstance(node.args[0], ast.JoinedStr)
            and any(isinstance(part, ast.Constant) and "curl -fsSL" in str(part.value)
                    for part in node.args[0].values)
        ]
        self.assertEqual(len(register_outputs), 1)
        parts = register_outputs[0].args[0].values
        self.assertTrue(any(isinstance(part, ast.Constant) and "| sudo sh" in str(part.value)
                            for part in parts))
        self.assertTrue(any(isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                            and part.value.id == "url" for part in parts))


if __name__ == "__main__":
    unittest.main()
