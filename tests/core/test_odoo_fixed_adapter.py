"""Offline checks of the fixed Odoo deploy.sh adapter."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/gway-repository-deploy-odoo-gelectriic.py"
spec = importlib.util.spec_from_file_location("odoo_fixed_adapter", SCRIPT)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
SHA = "a" * 40


class FixedAdapterTests(unittest.TestCase):
    def test_rejects_root_and_invalid_sha_before_shell(self):
        with patch.object(adapter.os, "geteuid", return_value=0):
            with self.assertRaises(PermissionError):
                adapter.run_fixed_deploy(SHA)
        with patch.object(adapter.os, "geteuid", return_value=1000):
            with self.assertRaises(ValueError):
                adapter.run_fixed_deploy("main;id")

    def test_fixed_checkout_and_no_args(self):
        calls = []
        def fake_run(argv, **kwargs):
            calls.append(argv)
            if argv[-2:] == ["--verify", "HEAD"]:
                return SimpleNamespace(stdout=SHA)
            if argv[-2:] == ["branch", "--show-current"]:
                return SimpleNamespace(stdout="main")
            if argv[-2:] == ["status", "--porcelain"]:
                return SimpleNamespace(stdout="")
            return SimpleNamespace(stdout="")
        with (patch.object(adapter.os, "geteuid", return_value=1000),
              patch.object(Path, "is_symlink", return_value=False),
              patch.object(Path, "is_dir", return_value=True),
              patch.object(Path, "is_file", return_value=True)):
            self.assertEqual(adapter.run_fixed_deploy(SHA, run=fake_run)["status"], "verified")
        self.assertTrue(any(argv[:2] == ["/bin/sh", "/opt/odoo-gelectriic/source/deploy.sh"]
                            and len(argv) == 2 for argv in calls))
        self.assertTrue(any("is-installed" in argv for argv in calls))


if __name__ == "__main__":
    unittest.main()
