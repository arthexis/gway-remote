"""Regression tests for the fixed recipe boundary; no remote execution."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import stat

from gway_remote.manual_deploy_recipe import recipe_argv, execute_recipe, repository_installer_argv, repository_installer_preview

SHA = "a" * 40


class RecipeTests(unittest.TestCase):
    def test_repository_owned_installer_requires_protected_registry(self):
        repo, node = "arthexis/odoo-gelectriic", "gway-001"
        with self.assertRaises((PermissionError, FileNotFoundError)):
            repository_installer_argv(repo, node, SHA, registry="/nonexistent/registry")
        row = {"repository": repo, "node": node,
               "entrypoint": "/usr/local/libexec/gway-repository-deploy-odoo-gelectriic",
               "enabled": True}
        trusted = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        def fake_lstat(path):
            return trusted if str(path) == row["entrypoint"] else directory
        with (patch("gway_remote.manual_deploy_recipe._trusted_registry", return_value=[row]),
              patch("gway_remote.manual_deploy_recipe.Path.lstat", autospec=True,
                    side_effect=fake_lstat)):
            self.assertEqual(repository_installer_argv(repo, node, SHA),
                             [row["entrypoint"], SHA])
            for invalid_repo, invalid_node, revision in (
                ("arthexis/unknown", node, SHA),
                (repo, "gway-002", SHA),
                (repo, node, "main"),
                (repo, node, SHA + ";sh"),
            ):
                with self.assertRaises((ValueError, PermissionError)):
                    repository_installer_argv(invalid_repo, invalid_node, revision)
        with patch("gway_remote.manual_deploy_recipe._trusted_registry", return_value=[{**row, "enabled": False}]):
            with self.assertRaises(PermissionError):
                repository_installer_argv(repo, node, SHA)

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
