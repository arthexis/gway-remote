"""Regression: MCP deployment tasks remain unique and structurally complete.

Full YAML parsing is covered by the existing Ansible syntax CI job; this
unit test deliberately requires only the Python standard library.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "ansible/roles/gway_remote/tasks/node-mcp-deploy.yml"


class DeploymentTasksYamlTests(unittest.TestCase):
    def test_no_duplicate_task_blocks(self):
        content = TASKS.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        task_names = re.findall(r"^- name: (.+)$", content, re.MULTILINE)
        self.assertGreater(len(task_names), 0)
        self.assertEqual(len(task_names), len(set(task_names)))
        # Every task must supply exactly one Ansible module or action.
        blocks = re.split(r"(?=^- name: )", content, flags=re.MULTILINE)[1:]
        self.assertEqual(len(blocks), len(task_names))
        for block in blocks:
            modules = re.findall(r"^  ansible\.builtin\.[a-z_]+:", block, re.MULTILINE)
            self.assertEqual(len(modules), 1, block.splitlines()[0])
        self.assertNotIn("\n)\n", content)


if __name__ == "__main__":
    unittest.main()
