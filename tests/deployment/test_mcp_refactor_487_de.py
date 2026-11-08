"""Deployment safety and effective-catalog contracts for #487 D+E."""
from pathlib import Path
import subprocess
import unittest

from gway_remote.mcp_bearer_gateway import inspect_federated_catalog
from gway_remote.mcp_tool_scope import required_scope

from tests.helpers.mcp_deployment import ROOT, PLAYBOOK


from tests.helpers.mcp_federation import FederationCatalogFixture, fixture_tool


def federation():
    return FederationCatalogFixture([
        fixture_tool('fixture__read', read=True),
        fixture_tool('fixture__execute'),
    ])


class MCPRefactorDeploymentContracts(unittest.TestCase):
    def test_effective_tools_list_matches_inspection(self):
        builtins = [{"name": "mcp_catalog_inspect", "inputSchema": {"type": "object"}}]
        listed, routes = federation().discover(builtins=builtins)
        inspected = inspect_federated_catalog(federation(), builtins=builtins)
        self.assertEqual([t["name"] for t in listed],
                         [t["name"] for t in inspected["tools"]])
        self.assertEqual(set(routes), {"fixture__read", "fixture__execute"})
        scopes = {t["name"]: t["required_scope"] for t in inspected["tools"]}
        self.assertEqual(scopes["fixture__read"], "gway:read")
        self.assertEqual(scopes["fixture__execute"], "gway:execute")
        self.assertTrue(all("inputSchema" not in tool for tool in inspected["tools"]))

    def test_production_playbook_has_release_rollback_and_idempotence_guards(self):
        content = PLAYBOOK.read_text()
        for invariant in (
            "mcp_target_sha", "previous_release.stdout", "active_release.stdout",
            "Restore previous immutable release pointer", "Restart restored user MCP backend",
            "when: previous_release.stdout != 'releases/' ~ mcp_target_sha",
            "changed_when: false", "is-active", "gway-remote-mcp.service",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, content)

    def test_production_playbook_ansible_syntax(self):
        import shutil
        if shutil.which("ansible-playbook") is None:
            self.skipTest("ansible-core unavailable")
        command = ["ansible-playbook", "--syntax-check", "-i", "localhost,",
                   str(PLAYBOOK)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
