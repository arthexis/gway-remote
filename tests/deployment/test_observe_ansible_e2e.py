"""Real ansible-playbook E2E against disposable local inventory; no deploy."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/deployment/fixtures/observe_e2e"


@unittest.skipUnless(os.environ.get("GWAY_OBSERVE_RUN_E2E") == "1", "opt-in CI E2E")
class AnsibleObservationE2E(unittest.TestCase):
    def test_allowed_denied_repeatability_and_errors(self):
        with tempfile.TemporaryDirectory(prefix="observe-e2e-") as directory:
            root = Path(directory)
            inventory = root / "inventory.yml"
            hostname = socket.gethostname().split(".", 1)[0]
            env = {**os.environ,
                   "GWAY_OBSERVE_E2E": "1",
                   "GWAY_OBSERVE_INVENTORY": str(inventory),
                   "PYTHONPATH": os.pathsep.join((str(FIXTURE), str(ROOT)))}
            command = ["ansible-playbook", "-i", "localhost,", "-c", "local",
                       str(ROOT / "ansible/observe-deployment.yml"),
                       "-e", "observation_component=gway-lcd-sound"]

            def inventory_for(allowed):
                entries = "\n".join(f"        - {name}" for name in allowed)
                inventory.write_text(
                    f"all:\n  hosts:\n    {hostname}:\n"
                    f"      remote_managed_repositories:\n{entries or '        []'}\n",
                    encoding="utf-8")

            def run():
                return subprocess.run(command, cwd=ROOT, env=env, text=True,
                                      capture_output=True, timeout=90)

            inventory_for(["arthexis/gway-lcd-sound"])
            first, second = run(), run()
            for result in (first, second):
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("changed=0", result.stdout)
                self.assertIn("schema_version", result.stdout)
                self.assertIn("arthexis/gway-lcd-sound", result.stdout)
                self.assertIn("runtime_state", result.stdout)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(list(root.iterdir()), [inventory])

            inventory_for(["arthexis/ocpp-csms"])
            denied = run()
            self.assertNotEqual(denied.returncode, 0)
            self.assertNotIn("schema_version", denied.stdout)
            self.assertIn("changed=0", denied.stdout)

            inventory_for(["arthexis/gway-lcd-sound"])
            inventory.unlink()
            missing = run()
            self.assertNotEqual(missing.returncode, 0)
            self.assertNotIn("schema_version", missing.stdout)


if __name__ == "__main__":
    unittest.main()
