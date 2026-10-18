"""RFID registration is consistent across deployment entry points."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import __main__ as cli
from gway_remote.best_effort import INSTALLERS, execute
from gway_remote.deploy_dispatch import TARGETS as DISPATCH_TARGETS
from gway_remote.reconcile import TARGETS

SHA = "a" * 40


class RfidDeploymentTests(unittest.TestCase):
    def test_registry_consistency(self):
        names = [name for name, _ in TARGETS]
        self.assertIn("gway-rfid", names)
        self.assertEqual(("all", *names), DISPATCH_TARGETS)
        self.assertEqual(set(names), set(INSTALLERS))
        self.assertEqual(INSTALLERS["gway-rfid"], "deploy_rfid")
        cli.validate("rfid-deploy", "arthexis/gway-rfid", SHA)
        with self.assertRaises(ValueError):
            cli.validate("rfid-deploy", "arthexis/ocpp-csms", SHA)

    def test_rfid_uses_pinned_canonical_wrapper(self):
        commands = []
        with patch("gway_remote.__main__.subprocess.run", side_effect=lambda cmd, **kw: commands.append(cmd)), \
             patch("gway_remote.__main__.subprocess.check_output", return_value=SHA):
            cli.deploy_rfid(SHA)
        self.assertEqual(commands[-1], ["sh", "./deploy.sh"])

    def test_mismatch_prevents_install(self):
        commands = []
        with patch("gway_remote.__main__.subprocess.run", side_effect=lambda cmd, **kw: commands.append(cmd)), \
             patch("gway_remote.__main__.subprocess.check_output", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "RFID checkout SHA mismatch"):
                cli.deploy_rfid(SHA)
        self.assertNotIn(["sh", "./deploy.sh"], commands)

    def test_one_target_only(self):
        calls = []
        installers = {name: lambda sha, name=name: calls.append(name) for name, _ in TARGETS}
        with tempfile.TemporaryDirectory() as temp, \
             patch("gway_remote.best_effort.main_head", return_value=SHA), \
             patch("gway_remote.best_effort.ci_for_head", return_value="success"):
            result = execute(object(), None, installers, directory=Path(temp),
                             deploy_all=True, target="gway-rfid")
        self.assertEqual(result["decision"], "completed")
        self.assertEqual(calls, ["gway-rfid"])


if __name__ == "__main__":
    unittest.main()
