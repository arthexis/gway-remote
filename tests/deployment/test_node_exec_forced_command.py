"""Offline forced-command boundary tests: never launch a caller-selected shell."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/node-exec-forced-command.py"


class ForcedCommandTests(unittest.TestCase):
    def test_rejects_missing_or_arbitrary_ssh_command(self):
        for command in (None, "", "id", "gway-exec-protocol-v1; id"):
            with self.subTest(command=command):
                env = {"PATH": "/usr/bin:/bin", "SSH_CONNECTION": "a b c d"}
                if command is not None:
                    env["SSH_ORIGINAL_COMMAND"] = command
                p = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                                   capture_output=True, timeout=5)
                self.assertEqual(p.returncode, 1)
                self.assertEqual(p.stdout, b"")

    def test_entrypoint_does_not_invoke_shell_or_sudo(self):
        source = SCRIPT.read_text()
        self.assertIn("os.execve", source)
        self.assertIn("node_exec_protocol", source)
        for forbidden in ("shell=True", "os.system(", "sudo -u",
                          "subprocess.run(", "/bin/sh", "SSH_AUTH_SOCK"):
            self.assertNotIn(forbidden, source)

    def test_opt_in_installs_entrypoint_before_key(self):
        recipe = (SCRIPT.parents[1] /
                  "ansible/roles/gway_remote/tasks/node-exec-opt-in.yml").read_text()
        self.assertLess(recipe.index("Install reviewed fixed-command entrypoint"),
                        recipe.index("Install dedicated restricted executor key"))
        self.assertIn("exclusive: false", recipe)
        self.assertIn("manage_dir: false", recipe)


if __name__ == "__main__":
    unittest.main()
