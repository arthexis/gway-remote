"""Node-owned manifests are discovered, never published by GWay Remote."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.mcp_deployment_contract import validate_deployment
from gway_remote.mcp_installed_providers import discover_installed_providers


SHA = "a" * 40
DEPLOY = {"schema": 1, "checkout": "/opt/sample",
          "runner": "/opt/sample/deploy.sh", "revision": SHA}


class ManifestDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="node-provider-manifest-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.providers = self.root / "providers"
        self.providers.mkdir()
        self.executable = self.root / "sample-mcp"
        self.executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.executable.chmod(0o755)
        self.manifest = self.providers / "sample.json"

    def _write_manifest(self, *, deployment=None):
        data = {"source_id": "sample", "revision": SHA,
                "executable": str(self.executable),
                "argv": [str(self.executable)]}
        if deployment is not None:
            data["deployment"] = deployment
        self.manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        self.manifest.chmod(0o644)

    def _discover(self):
        # Model root-owned /etc/gway-mcp-providers while the fixture remains
        # entirely unprivileged and offline. No chmod/chown of real files.
        original = Path.lstat

        def trusted(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.providers or path == self.manifest:
                values = list(info)
                values[4] = 0
                return os.stat_result(values)
            return info

        with patch.object(Path, "lstat", trusted):
            return discover_installed_providers(self.providers)

    def test_v1_manifest_discovered_without_legacy_registration(self):
        self._write_manifest()
        original = self.manifest.read_bytes()
        registrations = self._discover()
        self.assertEqual(len(registrations), 1)
        self.assertEqual(registrations[0].source_id, "sample")
        self.assertEqual(registrations[0].revision, SHA)
        self.assertIsNone(registrations[0].deployment)
        self.assertEqual(original, self.manifest.read_bytes())

    def test_v2_manifest_deployment_is_validated_without_publication(self):
        self._write_manifest(deployment=DEPLOY)
        before = self.manifest.read_bytes()
        registration = self._discover()[0]
        self.assertEqual(validate_deployment(registration.deployment), DEPLOY)
        self.assertEqual(before, self.manifest.read_bytes())

    def test_untrusted_or_invalid_manifest_fails_closed_without_repair(self):
        self._write_manifest(deployment=DEPLOY)
        self.manifest.chmod(0o666)
        with self.assertRaisesRegex(ValueError, "untrusted provider manifest"):
            self._discover()
        self.manifest.chmod(0o644)
        self.manifest.write_text('{"source_id":"sample","unexpected":true}')
        with self.assertRaisesRegex(ValueError, "invalid provider manifest"):
            self._discover()
        self.manifest.unlink()
        self.manifest.symlink_to(self.executable)
        with self.assertRaisesRegex(ValueError, "untrusted provider manifest"):
            self._discover()

    def test_uninstall_removes_discovery_without_remote_recreation(self):
        self._write_manifest()
        self.assertEqual(len(self._discover()), 1)
        self.manifest.unlink()
        self.assertEqual(self._discover(), ())


if __name__ == "__main__":
    unittest.main()
