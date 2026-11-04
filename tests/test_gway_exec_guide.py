"""Regression tests for the restricted MCP host-local guide export."""
import importlib.util
from pathlib import Path
import os
import stat
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "gway-exec-guide"
spec = importlib.util.spec_from_loader("gway_exec_guide", loader=None)
guide = importlib.util.module_from_spec(spec)
exec(compile(SOURCE.read_text(), str(SOURCE), "exec"), guide.__dict__)


class GuideExportTests(unittest.TestCase):
    def test_missing_or_untrusted_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(guide.entries(Path(root)), {})

    def test_private_user_home_not_indexed(self):
        self.assertNotIn("/home/arthe", str(guide.EXPORT_DIR))
        self.assertNotIn("/home/arthe", SOURCE.read_text())

    def test_expected_interface(self):
        self.assertEqual(guide.main(["--invalid"]), 2)
        self.assertEqual(guide.main(["search", "__impossible_command__"]), 1)
        self.assertEqual(guide.main(["where", "__impossible_command__"]), 1)
        self.assertEqual(guide.main([]), 0)

    def test_symlink_and_relative_path_rejected(self):
        self.assertFalse(guide.trusted_file(Path("relative-script")))
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "command"
            target.write_text("#!/bin/sh\n")
            target.chmod(0o755)
            link = Path(root) / "alias"
            link.symlink_to(target)
            self.assertFalse(guide.trusted_file(link))


if __name__ == "__main__":
    unittest.main()
