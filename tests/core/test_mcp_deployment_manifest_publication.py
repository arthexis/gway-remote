"""Offline manifest publication: the installed provider file is the only deploy registry."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.mcp_deployment_contract import validate_deployment

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "converge-mcp-manifests.py"
spec = importlib.util.spec_from_file_location("converge_mcp_manifests", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SHA = "a" * 40
BASE = {"source_id": "sample", "revision": SHA,
        "executable": "/opt/sample/bin/mcp",
        "argv": ["/opt/sample/bin/mcp"]}
DEPLOY = {"schema": 1, "checkout": "/opt/sample",
          "runner": "/opt/sample/deploy.sh", "revision": SHA}


class ManifestDeploymentTests(unittest.TestCase):
    def test_deployment_published_in_same_manifest_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(module, "DEST", Path(tmp)):
            item = {**BASE, "deployment": DEPLOY}
            self.assertTrue(module.publish(item))
            path = Path(tmp) / "sample.json"
            self.assertEqual(json.loads(path.read_text())["deployment"], DEPLOY)
            self.assertFalse(module.publish(item))
            self.assertEqual(validate_deployment(json.loads(path.read_text())["deployment"]), DEPLOY)

    def test_legacy_provider_remains_readable_without_deploy(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(module, "DEST", Path(tmp)):
            self.assertTrue(module.publish(BASE))
            self.assertNotIn("deployment", json.loads((Path(tmp) / "sample.json").read_text()))

    def test_invalid_deployment_never_replaces_existing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(module, "DEST", Path(tmp)):
            module.publish({**BASE, "deployment": DEPLOY})
            path = Path(tmp) / "sample.json"
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                module.publish({**BASE, "deployment": {**DEPLOY, "run_as": "root"}})
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
