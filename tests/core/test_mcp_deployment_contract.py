"""Deployment metadata validation; no process execution or live provider changes."""
import unittest

from gway_remote.mcp_deployment_contract import validate_deployment
from gway_remote.mcp_source_registry import SourceRegistration

SHA = "a" * 40
VALID = {
    "schema": 1, "checkout": "/opt/managed/agentops",
    "runner": "/opt/managed/agentops/deploy.sh",
    "run_as": "arthe", "revision": SHA,
}


class DeploymentDeclarationTests(unittest.TestCase):
    def test_valid_declaration(self):
        self.assertEqual(validate_deployment(dict(VALID)), VALID)

    def test_rejects_unsafe_declarations(self):
        mutations = (
            {"runner": "/bin/sh"}, {"runner": "/opt/managed/agentops/../other"},
            {"runner": "/opt/managed/agentops/deploy.sh;touch /tmp/pwn"},
            {"checkout": "/opt/managed/../agentops"},
            {"run_as": "root"}, {"revision": "main"},
            {"schema": True}, {"schema": 2}, {"extra": "ignored"},
        )
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_deployment({**VALID, **change})

    def test_legacy_registration_remains_valid(self):
        base = dict(source_id="agentops", revision=SHA,
                    executable="/opt/agentops/bin/mcp",
                    argv=("/opt/agentops/bin/mcp",), run_as="arthe", enabled=True)
        self.assertIsNone(SourceRegistration(**base).deployment)
        self.assertEqual(SourceRegistration(**base, deployment=dict(VALID)).deployment, VALID)
        with self.assertRaises(ValueError):
            SourceRegistration(**base, deployment={**VALID, "revision": "main"})


if __name__ == "__main__":
    unittest.main()
