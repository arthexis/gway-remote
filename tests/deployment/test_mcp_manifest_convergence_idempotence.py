"""Regression: Remote deploy never mutates Odoo/AgentOps-owned MCP manifests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.helpers.mcp_deployment import ROOT, PLAYBOOK, manifest_snapshot


RETIRED = ROOT / "scripts/converge-mcp-manifests.py"


class ManifestOwnershipTests(unittest.TestCase):
    def test_ansible_only_discovers_installed_manifests(self):
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("discover_installed_providers", playbook)
        self.assertIn("Verify installed MCP manifests are discoverable", playbook)
        self.assertNotIn("converge-mcp-manifests.py", playbook)
        self.assertNotIn("manifest_convergence", playbook)
        # The legacy policy is still validated for backwards compatibility,
        # but it must not be used to publish installed node-owned manifests.
        self.assertIn("GWAY_MCP_SOURCE_POLICY", playbook)
        self.assertIn("source_policy.stat.isreg", playbook)
        self.assertNotIn("/etc/gway-mcp-providers/odoo.json", playbook)
        self.assertNotIn("/etc/gway-mcp-providers/agentops.json", playbook)

    def test_first_and_second_legacy_convergence_attempts_leave_manifests_untouched(self):
        with tempfile.TemporaryDirectory(prefix="mcp-provider-owner-") as temp:
            root = Path(temp)
            providers = root / "providers"
            providers.mkdir()
            legacy = root / "sources.json"
            old_sha, new_sha = "b" * 40, "d" * 40
            legacy.write_text(json.dumps({"sources": [{
                "registration": {
                    "source_id": "odoo", "revision": old_sha,
                    "executable": "/opt/old/odoo-mcp",
                    "argv": ["/opt/old/odoo-mcp"], "enabled": True
                }
            }]}), encoding="utf-8")
            # Model manifests authored by their *own* installers.
            for name in ("odoo", "agentops"):
                path = providers / (name + ".json")
                path.write_text(json.dumps({
                    "source_id": name, "revision": new_sha,
                    "executable": "/opt/" + name + "/bin/mcp",
                    "argv": ["/opt/" + name + "/bin/mcp"]
                }) + "\n", encoding="utf-8")
                path.chmod(0o644)
            before = {p.name: manifest_snapshot(p) for p in providers.iterdir()}
            legacy_before = manifest_snapshot(legacy)
            env = {**os.environ, "GWAY_MCP_SOURCE_POLICY": str(legacy)}
            for attempt in (1, 2):
                # Even an obsolete caller attempting the old entrypoint must
                # fail closed, not downgrade Odoo or overwrite/delete AgentOps.
                result = subprocess.run(
                    [sys.executable, "-I", str(RETIRED)], cwd=root,
                    env=env, capture_output=True, text=True, timeout=10)
                with self.subTest(attempt=attempt):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("retired", result.stderr)
                    self.assertEqual(before, {
                        p.name: manifest_snapshot(p) for p in providers.iterdir()})
                    self.assertEqual(legacy_before, manifest_snapshot(legacy))
            # A missing provider must not be resurrected from stale policy.
            (providers / "odoo.json").unlink()
            expected = {p.name: manifest_snapshot(p) for p in providers.iterdir()}
            result = subprocess.run([sys.executable, "-I", str(RETIRED)],
                                    cwd=root, env=env, capture_output=True,
                                    text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(expected, {
                p.name: manifest_snapshot(p) for p in providers.iterdir()})
            self.assertFalse((providers / "odoo.json").exists())

    def test_legacy_writer_is_not_importable_as_a_publication_api(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("retired_mcp_migration", RETIRED)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertFalse(hasattr(module, "publish"))
        self.assertFalse(hasattr(module, "manifest_is_current"))
        with self.assertRaisesRegex(SystemExit, "retired"):
            module.main()


if __name__ == "__main__":
    unittest.main()
