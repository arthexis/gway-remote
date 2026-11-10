"""Ansible lifecycle and provider failure-isolation regression (#474)."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers.mcp_deployment import ansible_changed_count
from gway_remote.mcp_node_providers import provider_list, dispatch_node_provider_request
from gway_remote.mcp_installed_providers import discover_installed_providers
from gway_remote.mcp_gateway_federation import FederatedProviders
from gway_remote.mcp_source_registry import SourceRegistration
from gway_remote.mcp_source_stdio import list_source_tools


class MCPProviderLifecycleAnsibleTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-core unavailable")
    def test_ansible_fixture_lifecycle(self):
        playbook = Path(__file__).resolve().parents[2] / "ansible/playbooks/test-mcp-provider-lifecycle.yml"
        with tempfile.TemporaryDirectory(prefix="gway474-", dir="/tmp") as temporary:
            root = Path(temporary)
            directory = root / "providers"

            # Only the synthetic manifest/directory are represented as root
            # owned. No sudo, chown, systemd, node SSH or production paths.
            actual_lstat = Path.lstat

            def trusted_fixture_lstat(path):
                info = actual_lstat(path)
                if path == directory or (path.parent == directory
                                         and path.name == "fixture474.json"):
                    return SimpleNamespace(st_uid=0, st_mode=info.st_mode,
                                           st_size=info.st_size)
                return info

            def installed():
                with patch.object(Path, "lstat", trusted_fixture_lstat):
                    return discover_installed_providers(directory)

            class FixtureTransport:
                """Simulate an authenticated node transport, never a real SSH call."""
                def invoke(self, node, request, *, trusted_scope):
                    if node != "gway-001":
                        raise AssertionError("unexpected node")
                    return dispatch_node_provider_request(
                        installed(), request, node_id=node, trusted_scope=trusted_scope)

            gateway = FederatedProviders(
                transport=FixtureTransport(), nodes=lambda: ("gway-001",))

            def verify_version(version):
                expected = "fixture474__ping_" + version
                registrations = installed()
                self.assertEqual(len(registrations), 1)
                self.assertEqual(registrations[0].revision,
                                 ("a" if version == "v1" else "b") * 40)
                catalog, routes = gateway.discover()
                self.assertEqual([item["name"] for item in catalog], [expected])
                self.assertEqual(routes[expected],
                                 ("gway-001", "fixture474", "ping_" + version, "read"))
                reply = gateway.call(expected, {}, authorized_scope="read")
                self.assertEqual(reply["content"], [{"type": "text", "text": "ok"}])

            def converge(version):
                proc = subprocess.run(
                    ["ansible-playbook", "-i", "localhost,", str(playbook), "-e",
                     json.dumps({"fixture_dir": str(directory), "fixture_version": version})],
                    capture_output=True, text=True, timeout=90, check=False,
                    env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(root / "ansible-tmp")})
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                return proc.stdout

            self.assertEqual(ansible_changed_count(converge("v1")), 3)
            verify_version("v1")
            self.assertEqual(ansible_changed_count(converge("v1")), 0)
            verify_version("v1")

            self.assertEqual(ansible_changed_count(converge("v2")), 2)
            verify_version("v2")
            self.assertEqual(ansible_changed_count(converge("v2")), 0)
            verify_version("v2")
            with self.assertRaisesRegex(ValueError, "invalid_provider_call"):
                gateway.call("fixture474__ping_v1", {}, authorized_scope="read")

            self.assertEqual(ansible_changed_count(converge("v1")), 2)
            verify_version("v1")
            manifest_path = directory / "fixture474.json"
            original = manifest_path.read_bytes()
            self.assertEqual(json.loads(original)["revision"], "a" * 40)
            self.assertIn("ping_v1", (directory / "fixture.py").read_text())

            # A published but invalid manifest must fail closed, rather than
            # creating a visible/callable provider from the executable alone.
            manifest_path.write_text('{"source_id":"fixture474","unexpected":true}')
            with self.assertRaisesRegex(ValueError, "invalid provider manifest"):
                gateway.discover()
            manifest_path.write_bytes(original)
            verify_version("v1")

            # Unpublishing the manifest removes the tool from discovery even
            # though the executable is still installed and executable.
            manifest_path.unlink()
            self.assertEqual(installed(), ())
            self.assertEqual(gateway.discover(), ([], {}))

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
