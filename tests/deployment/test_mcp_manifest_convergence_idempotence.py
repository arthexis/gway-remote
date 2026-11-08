"""#487: repeated manifest convergence preserves inode, mtime and bytes."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/converge-mcp-manifests.py'
spec = importlib.util.spec_from_file_location('mcp_manifest_convergence', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ManifestConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {'source_id': 'fixture', 'revision': 'a' * 40,
                         'executable': '/opt/example/bin/mcp',
                         'argv': ['/opt/example/bin/mcp']}

    def test_repeated_publish_preserves_inode_mtime_and_bytes(self):
        original_check = module.manifest_is_current
        with patch.object(module, 'DEST', self.root):
            self.assertTrue(module.publish(self.manifest))
            path = self.root / 'fixture.json'
            first, original = path.stat(), path.read_bytes()
            self.assertTrue(original_check(path, original, owner_uid=os.getuid()))
            with patch.object(module, 'manifest_is_current',
                              side_effect=lambda p, b: original_check(p, b, owner_uid=os.getuid())):
                self.assertFalse(module.publish(self.manifest))
                self.assertTrue(module.publish(dict(self.manifest, revision='b' * 40)))
            second = path.stat()
            self.assertNotEqual(first.st_ino, second.st_ino)
            self.assertEqual(json.loads(path.read_text())['revision'], 'b' * 40)

    def test_identical_publish_does_not_touch_metadata(self):
        original_check = module.manifest_is_current
        with patch.object(module, 'DEST', self.root):
            module.publish(self.manifest)
            path = self.root / 'fixture.json'
            before, data = path.stat(), path.read_bytes()
            with patch.object(module, 'manifest_is_current',
                              side_effect=lambda p, b: original_check(p, b, owner_uid=os.getuid())):
                self.assertFalse(module.publish(self.manifest))
            after = path.stat()
            self.assertEqual((before.st_ino, before.st_mtime_ns, data),
                             (after.st_ino, after.st_mtime_ns, path.read_bytes()))

    def test_symlink_is_never_trusted(self):
        target = self.root / 'target'
        target.write_text('{}')
        path = self.root / 'fixture.json'
        path.symlink_to(target)
        self.assertFalse(module.manifest_is_current(path, b'{}', owner_uid=os.getuid()))

    def test_ansible_reports_actual_change(self):
        playbook = (SCRIPT.parents[1] / 'ansible/playbooks/gway001-mcp-runtime.yml').read_text()
        self.assertIn('register: manifest_convergence', playbook)
        self.assertIn("'changed=1' in manifest_convergence.stdout_lines", playbook)

if __name__ == '__main__':
    unittest.main()
