import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy.sh"


class DeployAnsibleVersionTests(unittest.TestCase):
    def _run(self, version, *arguments):
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            shim = bindir / "ansible-playbook"
            shim.write_text(
                "#!/bin/sh\n"
                "if [ \"${1:-}\" = --version ]; then\n"
                f"  printf '%s\\n' 'ansible [core {version}]'\n"
                "  exit 0\n"
                "fi\n"
                "exit 0\n"
            )
            shim.chmod(stat.S_IRWXU)
            environment = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
            return subprocess.run(["sh", str(SCRIPT), *arguments], cwd=ROOT,
                                  env=environment, text=True, capture_output=True)

    def test_rejects_ansible_core_older_than_minimum(self):
        result = self._run("2.11.12", "--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ansible Core 2.12 or newer is required", result.stderr)
        self.assertIn("sudo apt install ansible-core", result.stderr)

    def test_accepts_minimum_ansible_core(self):
        result = self._run("2.12.0", "--check")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
