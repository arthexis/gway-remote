"""#565 P3-C1 hermetic read-side GitHub collection catalog migration."""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gway_remote import github_state
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


SHA = "a" * 40
MERGED = datetime(2026, 11, 17, tzinfo=timezone.utc)


class GitHubCatalogP3C1Tests(unittest.TestCase):
    def test_collect_preserves_exact_seven_order_and_source_urls(self):
        calls = []
        attempts = {TARGETS[0][0]: SHA}
        with patch.object(github_state, "load_catalog", wraps=load_catalog) as loader, \
             patch.object(github_state, "main_head",
                          side_effect=lambda client, repository: calls.append(("head", repository)) or SHA), \
             patch.object(github_state, "main_arrival",
                          side_effect=lambda client, repository, sha: calls.append(("arrival", repository, sha)) or MERGED), \
             patch.object(github_state, "ci_for_head",
                          side_effect=lambda client, repository, sha: calls.append(("ci", repository, sha)) or "success"):
            result = github_state.collect(object(), attempts)
        loader.assert_called_once_with()
        self.assertEqual(len(result), 7)
        self.assertEqual([item.name for item in result], [name for name, _ in TARGETS])
        for item in result:
            self.assertEqual(item.sha, SHA)
            self.assertEqual(item.merged_at, MERGED)
            self.assertEqual(item.ci, "success")
        self.assertEqual(result[0].attempted_sha, SHA)
        self.assertTrue(all(item.attempted_sha is None for item in result[1:]))
        self.assertEqual(calls, [
            call for _, source in TARGETS for call in
            (("head", source), ("arrival", source, SHA), ("ci", source, SHA))
        ])

    def test_bad_catalog_fails_closed_before_network_and_attempt_iteration(self):
        class NoRead(dict):
            def get(self, *args):
                raise AssertionError("attempts accessed")
        with patch.object(github_state, "load_catalog",
                          side_effect=ValueError("catalog drift")) as loader, \
             patch.object(github_state, "main_head",
                          side_effect=AssertionError("GitHub I/O")) as head, \
             patch.object(github_state, "main_arrival",
                          side_effect=AssertionError("commit read")) as arrival, \
             patch.object(github_state, "ci_for_head",
                          side_effect=AssertionError("CI read")) as ci:
            with self.assertRaisesRegex(ValueError, "catalog drift"):
                github_state.collect(object(), NoRead({"ocpp-csms": SHA}))
            loader.assert_called_once_with()
            head.assert_not_called()
            arrival.assert_not_called()
            ci.assert_not_called()

    def test_collector_never_grants_deployment_or_writes(self):
        with patch.object(github_state, "load_catalog", wraps=load_catalog), \
             patch.object(github_state, "main_head", return_value=SHA), \
             patch.object(github_state, "main_arrival", return_value=MERGED), \
             patch.object(github_state, "ci_for_head", return_value="pending"):
            states = github_state.collect(object())
        self.assertEqual(len(states), len(TARGETS))
        self.assertTrue(all(state.ci == "pending" for state in states))
        self.assertTrue(all(not hasattr(state, "deployable") for state in states))

    def test_catalog_is_not_loaded_at_module_import_time(self):
        tree = ast.parse(inspect.getsource(github_state))
        for statement in tree.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            self.assertFalse(any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "load_catalog"
                for child in ast.walk(statement)
            ))

    def test_registry_parity_not_a_permission_grant(self):
        catalog = load_catalog()
        self.assertEqual(
            tuple((target.id, target.repository) for target in catalog.targets),
            TARGETS,
        )
        self.assertFalse(any(target.id == "ocpp-simulator" for target in catalog.targets))


if __name__ == "__main__":
    unittest.main()
