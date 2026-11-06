"""Contract tests for the read-only workspace inspector."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from gway_remote.workspace_inspect import SCHEMA, inspect_workspace


class WorkspaceInspectTests(unittest.TestCase):
    def test_unconfigured_repo_rejected(self):
        with self.assertRaises(ValueError):
            inspect_workspace("owner/other", {})

    def test_git_state_and_unknown_external_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
            result = inspect_workspace("owner/repo", {"owner/repo": str(root)}, node="test-node")
            self.assertEqual(result["schema"], SCHEMA)
            self.assertEqual(result["git"]["head"]["state"], "observed")
            self.assertEqual(result["git"]["clean_tracked"]["value"], True)
            self.assertEqual(result["ci"]["state"], "unknown")
            self.assertEqual(result["deployment"]["state"], "unknown")
            (root / "tracked.txt").write_text("initial")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            result = inspect_workspace("owner/repo", {"owner/repo": str(root)})
            self.assertEqual(result["git"]["clean_tracked"]["value"], False)


if __name__ == "__main__":
    unittest.main()
