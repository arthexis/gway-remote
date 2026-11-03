"""Agent Ops is a first-class appliance component but deployment never executes tasks."""
import unittest
from unittest.mock import patch
from gway_remote import __main__ as cli
from gway_remote.reconcile import TARGETS
from gway_remote.best_effort import INSTALLERS


class AgentOpsDeploymentTests(unittest.TestCase):
    def test_catalog_and_validator(self):
        self.assertIn(("gway-agent-ops", "arthexis/gway-agent-ops"), TARGETS)
        self.assertEqual(INSTALLERS["gway-agent-ops"], "deploy_agent_ops")
        self.assertIn("agent-ops-deploy", cli.TASKS)
        cli.validate("agent-ops-deploy", "arthexis/gway-agent-ops", "a" * 40)
        for repository in ("arthexis/ocpp-csms", "other/agent-ops"):
            with self.assertRaises(ValueError):
                cli.validate("agent-ops-deploy", repository, "a" * 40)

    def test_batch_target_installer_declared(self):
        self.assertTrue(callable(cli.deploy_agent_ops))

    def test_deployment_is_not_agent_execution(self):
        import inspect
        source = inspect.getsource(cli.deploy_agent_ops)
        self.assertIn("git", source)
        self.assertIn("Agent Ops checkout SHA mismatch", source)
        self.assertIn("sh\", \"./deploy.sh", source)
        self.assertNotIn("os.replace", source)
        self.assertNotIn("venv", source)
        self.assertNotIn('["agent", "issue"', source)
        self.assertNotIn('["agent", "adopt"', source)


if __name__ == "__main__":
    unittest.main()
