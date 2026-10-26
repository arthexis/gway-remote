"""Verify every appliance workflow job is gated by admission and the node."""
from pathlib import Path
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "appliance-deploy.yml"


class WorkflowAdmissionTests(unittest.TestCase):
    def test_all_jobs_require_successful_admission(self):
        data = yaml.safe_load(WORKFLOW.read_text())
        jobs = data["jobs"]
        self.assertIn("admission", jobs)
        for name, job in jobs.items():
            if name == "admission":
                continue
            with self.subTest(job=name):
                needs = job.get("needs", [])
                if isinstance(needs, str):
                    needs = [needs]
                self.assertIn("admission", needs)
                self.assertIn("needs.admission.result == 'success'", job.get("if", ""))
                self.assertIn("inputs.node == 'gway-001'", job.get("if", ""))
                self.assertIn("gway-001", job.get("runs-on", []))

    def test_workflow_default_and_available_nodes(self):
        data = yaml.safe_load(WORKFLOW.read_text())
        # PyYAML may parse the unquoted YAML 1.1 'on' key as boolean True.
        triggers = data.get("on", data.get(True))
        node = triggers["workflow_dispatch"]["inputs"]["node"]
        self.assertEqual(node["default"], "gway-001")
        self.assertEqual(node["type"], "choice")
        self.assertIn("customer.gelectriic.com", node["options"])


if __name__ == "__main__":
    unittest.main()
