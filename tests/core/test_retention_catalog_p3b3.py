"""P3-B3: hermetic checked-catalog enumeration for retention preview."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gway_remote import retention_preview
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


class RetentionCatalogP3B3Tests(unittest.TestCase):
    def _preview(self, repository=None, roots=None):
        with tempfile.TemporaryDirectory() as home:
            return retention_preview.preview(
                repository, home=home, roots={} if roots is None else roots
            )

    def test_legacy_order_schema_and_no_deletion_authority(self):
        report = self._preview()
        known = [name for name, _ in TARGETS]
        self.assertEqual(report["schema"], "gway-remote/retention-preview/v1")
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["deletion_enabled"])
        self.assertEqual([row["name"] for row in report["targets"]], known)
        self.assertTrue(all(row["status"] == "unsupported" for row in report["targets"]))
        self.assertTrue(all(row["releases"] == [] and row["potential_bytes"] == 0
                            for row in report["targets"]))
        self.assertNotIn("ocpp-simulator", known)

    def test_specific_repository_and_unregistered_rejected(self):
        report = self._preview("gway-bastion")
        self.assertEqual([row["name"] for row in report["targets"]], ["gway-bastion"])
        with self.assertRaisesRegex(ValueError, "unregistered target"):
            self._preview("ocpp-simulator")

    def test_checked_catalog_single_snapshot(self):
        original = load_catalog()
        with patch.object(retention_preview, "load_catalog",
                          return_value=original) as loader:
            self._preview()
        loader.assert_called_once_with()

    def test_catalog_failure_precedes_any_path_inspection(self):
        with patch.object(retention_preview, "load_catalog",
                          side_effect=ValueError("invalid catalog")) as loader, \
             patch.object(retention_preview.Path, "home",
                          side_effect=AssertionError("home read")) as home:
            with self.assertRaisesRegex(ValueError, "invalid catalog"):
                retention_preview.preview()
            loader.assert_called_once_with()
            home.assert_not_called()

    def test_fixed_roots_and_unsupported_behavior_unchanged(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / "missing-root"
            # A fixed test-owned path still reports absent and never authorizes deletion.
            report = retention_preview.preview(
                "ocpp-csms", home=home,
                roots={"ocpp-csms": ("absolute", str(root))}
            )
        row = report["targets"][0]
        self.assertEqual(row["status"], "absent")
        self.assertEqual(row["potential_bytes"], 0)
        self.assertEqual(row["releases"], [])
        self.assertFalse(report["deletion_enabled"])

    def test_no_eager_load_at_module_scope(self):
        tree = ast.parse(inspect.getsource(retention_preview))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            self.assertFalse(any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "load_catalog"
                for child in ast.walk(node)
            ))

    def test_checked_catalog_matches_existing_seven(self):
        self.assertEqual(
            tuple((target.id, target.repository) for target in load_catalog().targets),
            TARGETS,
        )


if __name__ == "__main__":
    unittest.main()
