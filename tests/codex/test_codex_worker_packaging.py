"""Verify Codex worker is reachable through the installed zipapp entrypoint."""
import subprocess
import sys
import tempfile
import unittest
import zipapp
from pathlib import Path


class WorkerPackagingTests(unittest.TestCase):
    def test_zipapp_exposes_codex_worker_command(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            import shutil
            shutil.copytree(root / "gway_remote", temp / "gway_remote")
            (temp / "__main__.py").write_text(
                "from gway_remote.__main__ import main\nmain()\n", encoding="utf-8"
            )
            archive = temp.parent / (temp.name + ".pyz")
            try:
                zipapp.create_archive(temp, archive, interpreter="/usr/bin/env python3")
                result = subprocess.run(
                    [sys.executable, str(archive), "codex-worker", "--help"],
                    capture_output=True, text=True, timeout=10
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("serve", result.stdout)
                self.assertIn("status", result.stdout)
            finally:
                archive.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
