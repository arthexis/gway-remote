"""Regression: deployment tasks must remain valid YAML with unique task names."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "ansible/roles/gway_remote/tasks/node-mcp-deploy.yml"

class DeploymentTasksYamlTests(unittest.TestCase):
    def test_yaml_parses_without_duplicate_task_blocks(self):
        content = TASKS.read_text(encoding="utf-8")
        tasks = yaml.safe_load(content)
        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 12)
        names = [task["name"] for task in tasks]
        self.assertEqual(len(names), len(set(names)))
        for task in tasks:
            self.assertIsInstance(task, dict)
            self.assertTrue(any(key.startswith("ansible.builtin.") for key in task))

if __name__ == "__main__":
    unittest.main()
