"""Prevent partially registered appliance deployment targets on gway-001."""
import pathlib
import re
import unittest

from gway_remote.reconcile import TARGETS
from gway_remote.best_effort import INSTALLERS
from gway_remote.deploy_dispatch import TARGETS as DISPATCH_TARGETS

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RepositoryOnboardingContractTests(unittest.TestCase):
    def test_catalog_installer_cli_parity(self):
        names = tuple(name for name, _ in TARGETS)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(INSTALLERS))
        self.assertEqual(("all", *names), DISPATCH_TARGETS)

    def test_workflow_choice_job_and_summary_parity(self):
        workflow = (ROOT / ".github/workflows/appliance-deploy.yml").read_text()
        choices = workflow.split("      repository:", 1)[1].split("\npermissions:", 1)[0]
        for name, _ in TARGETS:
            with self.subTest(repository=name):
                job = name.replace("-", "_")
                self.assertIn(f"          - {name}\n", choices)
                self.assertEqual(len(re.findall(rf"(?m)^  {re.escape(job)}:$", workflow)), 1)
                self.assertIn(f"deploy-batch --all --target {name}", workflow)
                self.assertIn(f'"{job}": "{name}"', workflow)
        self.assertNotIn("schedule:", workflow)

    def test_aeon_mud_admitted_only_on_gway001(self):
        inventory = (ROOT / "ansible/inventory/deployment.yml").read_text()
        controller = inventory.split("        gway-001:\n", 1)[1].split("    quality:\n", 1)[0]
        other_nodes = inventory.split("    quality:\n", 1)[1]
        self.assertEqual(controller.count("            - aeon-mud\n"), 1)
        self.assertNotIn("            - aeon-mud", other_nodes)
        self.assertEqual(dict(TARGETS)["aeon-mud"], "arthexis/aeon-mud")
        self.assertEqual(INSTALLERS["aeon-mud"], "deploy_aeon_mud")
        from gway_remote.probe_registry import PROBES
        self.assertEqual(PROBES["aeon-mud"].kind, "executable")
        self.assertTrue(PROBES["aeon-mud"].revision_from_executable)
        from gway_remote.deploy_dispatch import dispatch
        with self.assertRaises(ValueError):
            dispatch("aeon-mud", node="gway-002")

    def test_reports_admitted_on_gway001_only(self):
        inventory = (ROOT / "ansible/inventory/deployment.yml").read_text()
        pilot = inventory.split("        gway-001:\n", 1)[1].split("    quality:\n", 1)[0]
        remainder = inventory.split("    quality:\n", 1)[1]
        self.assertEqual(len(re.findall(r"(?m)^            - ocpp-reports$", pilot)), 1)
        self.assertNotIn("            - ocpp-reports", remainder)


if __name__ == "__main__":
    unittest.main()
