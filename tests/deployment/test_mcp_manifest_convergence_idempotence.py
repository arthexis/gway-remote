"""#487: repeated manifest convergence preserves inode, mtime and bytes."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers.mcp_deployment import (ROOT, PLAYBOOK, load_manifest_publisher,
                                         fixture_manifest, manifest_snapshot)
module = load_manifest_publisher()

class ManifestConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = fixture_manifest()

    def test_repeated_publish_preserves_inode_mtime_and_bytes(self):
        original_check = module.manifest_is_current
        with patch.object(module, 'DEST', self.root):
            self.assertTrue(module.publish(self.manifest))
            path = self.root / 'fixture.json'
            first_inode, _, original = manifest_snapshot(path)
            self.assertTrue(original_check(path, original, owner_uid=os.getuid()))
            with patch.object(module, 'manifest_is_current',
                              side_effect=lambda p, b: original_check(p, b, owner_uid=os.getuid())):
                self.assertFalse(module.publish(self.manifest))
                self.assertTrue(module.publish(dict(self.manifest, revision='b' * 40)))
            second_inode, _, _ = manifest_snapshot(path)
            self.assertNotEqual(first_inode, second_inode)
            self.assertEqual(json.loads(path.read_text())['revision'], 'b' * 40)

    def test_identical_publish_does_not_touch_metadata(self):
        original_check = module.manifest_is_current
        with patch.object(module, 'DEST', self.root):
            module.publish(self.manifest)
            path = self.root / 'fixture.json'
            before = manifest_snapshot(path)
            with patch.object(module, 'manifest_is_current',
                              side_effect=lambda p, b: original_check(p, b, owner_uid=os.getuid())):
                self.assertFalse(module.publish(self.manifest))
            self.assertEqual(before, manifest_snapshot(path))

    def test_symlink_is_never_trusted(self):
        target = self.root / 'target'
        target.write_text('{}')
        path = self.root / 'fixture.json'
        path.symlink_to(target)
        self.assertFalse(module.manifest_is_current(path, b'{}', owner_uid=os.getuid()))

    def test_ansible_reports_actual_change(self):
        playbook = PLAYBOOK.read_text()
        self.assertIn('register: manifest_convergence', playbook)
        self.assertIn("'changed=1' in manifest_convergence.stdout_lines", playbook)

if __name__ == '__main__':
    unittest.main()
