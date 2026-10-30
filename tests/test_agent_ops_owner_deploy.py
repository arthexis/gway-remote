"""Remote/owner deployment boundary for issue #306."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import __main__ as remote


class AgentOpsOwnerDelegationTests(unittest.TestCase):
    def test_delegates_to_canonical_owner_installer_and_verifies_installed_sha(self):
        sha = "a" * 40
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".local/share/gway-agent-ops/releases" / sha / "bin"
            root.mkdir(parents=True)
            (root / "agent").write_text("#!/bin/sh\nexit 0\n")
            entry = home / ".local/bin/agent"
            entry.parent.mkdir(parents=True)
            entry.symlink_to(root / "agent")
            def run(argv, **kwargs):
                calls.append(argv)
                if argv[:2] == ["git", "clone"]:
                    (Path(argv[-1]) / "deploy.sh").parent.mkdir(parents=True)
                    (Path(argv[-1]) / "deploy.sh").write_text("#!/bin/sh\nexit 0\n")
                return subprocess.CompletedProcess(argv, 0)
            with patch.object(remote.Path, "home", return_value=home), \
                 patch.object(remote.subprocess, "run", side_effect=run), \
                 patch.object(remote.subprocess, "check_output", return_value=sha+"\n"):
                remote.deploy_agent_ops(sha)
        self.assertTrue(any(args[:2] == ["sh", "./deploy.sh"] and
                            args[-2:] == ["--expected-sha", sha] for args in calls))
        self.assertFalse(any(args[:3] == ["python", "-m", "venv"] for args in calls))

    def test_missing_owner_wrapper_fails_closed(self):
        sha = "a" * 40
        def run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(remote.subprocess, "run", side_effect=run), \
             patch.object(remote.subprocess, "check_output", return_value=sha+"\n"):
            with self.assertRaises(RuntimeError):
                remote.deploy_agent_ops(sha)


if __name__ == "__main__":
    unittest.main()
