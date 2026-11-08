"""Ansible lifecycle and provider failure-isolation regression (#474)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.mcp_node_providers import provider_list
from gway_remote.mcp_source_registry import SourceRegistration
from gway_remote.mcp_source_stdio import list_source_tools


class MCPProviderLifecycleAnsibleTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-core unavailable")
    def test_ansible_fixture_lifecycle(self):
        playbook = Path(__file__).resolve().parents[2] / "ansible/playbooks/test-mcp-provider-lifecycle.yml"
        with tempfile.TemporaryDirectory(prefix="gway474-", dir="/tmp") as temporary:
            root = Path(temporary)
            directory = root / "providers"

            def converge(version):
                proc = subprocess.run(
                    ["ansible-playbook", "-i", "localhost,", str(playbook), "-e",
                     json.dumps({"fixture_dir": str(directory), "fixture_version": version})],
                    capture_output=True, text=True, timeout=90, check=False,
                    env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(root / "ansible-tmp")})
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                return proc.stdout

            self.assertIn("changed=3", converge("v1"))
            self.assertIn("changed=0", converge("v1"))
            self.assertIn("changed=2", converge("v2"))
            self.assertIn("changed=0", converge("v2"))
            self.assertIn("changed=2", converge("v1"))
            manifest = json.loads((directory / "fixture474.json").read_text())
            self.assertEqual(manifest["revision"], "a" * 40)
            self.assertIn("ping_v1", (directory / "fixture.py").read_text())
            (directory / "fixture474.json").unlink()
            self.assertFalse((directory / "fixture474.json").exists())

    def test_missing_and_timed_out_provider_are_isolated(self):
        with tempfile.TemporaryDirectory(prefix="gway474-", dir="/tmp") as temporary:
            missing = str(Path(temporary) / "missing")
            base = dict(source_id="fixture474", revision="a" * 40,
                        run_as="arthe", enabled=True)
            registration = SourceRegistration(executable=missing, argv=(missing,), **base)
            missing_result = provider_list([registration], node_id="gway-001")["providers"][0]
            self.assertEqual(missing_result["status"], "unavailable")
            self.assertEqual(missing_result["error"]["code"], "provider_unavailable")

            # The process deliberately does not speak MCP; enforce a short timeout.
            sleep = shutil.which("sleep")
            self.assertIsNotNone(sleep)
            hung = SourceRegistration(executable=sleep, argv=(sleep, "30"), **base)
            with patch("gway_remote.mcp_node_providers.list_source_tools",
                       side_effect=lambda r: list_source_tools(r, timeout=0.5)):
                results = provider_list([registration, hung], node_id="gway-001")["providers"]
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["error"]["code"], "provider_unavailable")
            self.assertEqual(results[1]["error"]["code"], "provider_timeout")


if __name__ == "__main__":
    unittest.main()
