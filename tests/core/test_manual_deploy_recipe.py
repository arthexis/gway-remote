"""Regression tests for the fixed recipe boundary; no remote execution."""
import unittest
from types import SimpleNamespace

from gway_remote.manual_deploy_recipe import recipe_argv, execute_recipe, repository_installer_argv, repository_installer_preview

SHA = "a" * 40


class RecipeTests(unittest.TestCase):
    def test_repository_owned_installer_is_dormant_and_fixed(self):
        with self.assertRaises(PermissionError):
            repository_installer_argv("arthexis/odoo-gelectriic", "gway-001", SHA)
        self.assertEqual(
            repository_installer_argv("arthexis/odoo-gelectriic", "gway-001",
                                      SHA, installed=True),
            ["/usr/local/libexec/gway-repository-deploy-odoo-gelectriic", SHA])
        for repo, node, revision in (
            ("arthexis/unknown", "gway-001", SHA),
            ("arthexis/odoo-gelectriic", "gway-002", SHA),
            ("arthexis/odoo-gelectriic", "gway-001", "main"),
            ("arthexis/odoo-gelectriic", "gway-001", SHA + ";sh"),
        ):
            with self.assertRaises((ValueError, PermissionError)):
                repository_installer_argv(repo, node, revision, installed=True)

    def test_allowlisted_fixed_recipe(self):
        argv = recipe_argv("arthexis/ocpp-reports", "gway-001", SHA)
        self.assertEqual(argv[-1], SHA)
        self.assertEqual(argv[0], "/usr/local/libexec/gway-deploy-ocpp-reports-gway-001")

    def test_no_arbitrary_shell_or_revision(self):
        for repo, node, sha in (
            ("arthexis/ocpp-csms", "gway-001", SHA),
            ("arthexis/ocpp-reports", "gway-004", SHA),
            ("arthexis/ocpp-reports", "gway-001", "main"),
            ("arthexis/ocpp-reports", "gway-001", SHA + ";id"),
        ):
            with self.subTest(repo=repo, node=node, sha=sha):
                with self.assertRaises((ValueError, PermissionError)):
                    recipe_argv(repo, node, sha)

    def test_bounded_subprocess_and_receipt(self):
        observed = []
        def fake_run(argv, **kwargs):
            observed.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        result = execute_recipe("arthexis/ocpp-reports", "gway-001", SHA, run=fake_run)
        self.assertEqual(result["state"], "succeeded")
        self.assertFalse(observed[0][1]["shell"])
        self.assertEqual(observed[0][1]["timeout"], 600)
