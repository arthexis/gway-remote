"""Offline forced-command boundary tests: never launch a caller-selected shell."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
import runpy
from unittest.mock import patch
from types import SimpleNamespace

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

    def test_valid_ssh_marker_execs_only_fixed_protocol_with_clean_env(self):
        class ExecReached(Exception):
            pass

        with patch("os.geteuid", return_value=1001), patch("os.getuid", return_value=1001), \
             patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir="/home/installer", pw_name="installer")), \
             patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "gway-exec-protocol-v1",
                                     "SSH_CONNECTION": "192.0.2.1 1000 192.0.2.2 22",
                                     "SSH_AUTH_SOCK": "/tmp/untrusted", "PYTHONPATH": "/tmp/untrusted"},
                        clear=True), \
             patch("os.execve", side_effect=ExecReached) as execve:
            with self.assertRaises(ExecReached):
                runpy.run_path(str(SCRIPT), run_name="__main__")
        executable, argv, env = execve.call_args.args
        self.assertEqual(executable, "/usr/bin/python3")
        self.assertEqual(argv, ["/usr/bin/python3", "-m", "gway_remote.node_exec_protocol"])
        self.assertEqual(env["USER"], "installer")
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertEqual(env["PYTHONPATH"], "/opt/gway-remote")

    def test_tty_and_empty_connection_rejected_before_exec(self):
        for env in ({"SSH_TTY": "/dev/pts/1", "SSH_CONNECTION": "x"},
                    {"SSH_CONNECTION": ""}):
            with self.subTest(env=env), \
                 patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "gway-exec-protocol-v1", **env}, clear=True), \
                 patch("os.geteuid", return_value=1001), patch("os.getuid", return_value=1001), \
                 patch("os.execve") as execve:
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(str(SCRIPT), run_name="__main__")
                self.assertEqual(raised.exception.code, 1)
                execve.assert_not_called()

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
