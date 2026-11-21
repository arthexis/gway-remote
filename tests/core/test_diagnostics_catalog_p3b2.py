"""P3-B2: diagnostics-only migration to the checked appliance catalog."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gway_remote import diagnostics
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


class DiagnosticsCatalogP3B2Tests(unittest.TestCase):
    def _exercise(self, name=None, *, catalog=None, lines=30):
        targets = tuple(SimpleNamespace(id=n) for n, _ in TARGETS)
        report = {
            "node": "fixture-node",
            "checked_at": "2026-11-17T00:00:00+00:00",
            "components": [
                {"name": n, "installation": "never-attempted", "health": "unknown",
                 "attempted_sha": None, "installed_sha": None, "error": None}
                for n, _ in TARGETS
            ],
        }
        with patch.object(diagnostics, "load_catalog",
                          return_value=SimpleNamespace(targets=targets) if catalog is None else catalog) as loader, \
             patch.object(diagnostics, "status", return_value=report) as status, \
             patch.object(diagnostics, "read_log", return_value="") as logs, \
             patch.object(diagnostics, "_systemd", return_value={"state": "not-configured"}) as systemd, \
             patch.object(diagnostics, "probe_for",
                          side_effect=lambda n: SimpleNamespace(service=None)):
            result = diagnostics.diagnose(name, directory=Path("/not-read"),
                                          lines=lines)
            return result, loader.call_count, status.call_count, logs.call_count, systemd.call_count

    def test_exact_order_schema_and_classification_for_every_known_target(self):
        report, loads, status_calls, logs, systemd = self._exercise()
        self.assertEqual(loads, 1)
        self.assertEqual(status_calls, 1)
        names = [n for n, _ in TARGETS]
        self.assertEqual([x["name"] for x in report["components"]], names)
        self.assertEqual(report["schema"], "gway-remote/diagnosis/v1")
        self.assertEqual(report["node"], "fixture-node")
        self.assertEqual(report["checked_at"], "2026-11-17T00:00:00+00:00")
        self.assertEqual(logs, len(names))
        self.assertEqual(systemd, len(names))
        for entry in report["components"]:
            self.assertEqual(entry["diagnosis"], "runtime-not-verified")
            self.assertEqual(entry["recent_installer_log"], "")
            self.assertEqual(entry["systemd"], {"state": "not-configured"})

    def test_selected_target_uses_one_catalog_load_one_log_and_probe(self):
        result, loads, status_calls, logs, systemd = self._exercise("gway-bastion")
        self.assertEqual([x["name"] for x in result["components"]], ["gway-bastion"])
        self.assertEqual((loads, status_calls, logs, systemd), (1, 1, 1, 1))
        self.assertEqual(result["components"][0]["diagnosis"], "runtime-not-verified")

    def test_module_does_not_eagerly_load_catalog(self):
        # Inspect the module AST rather than reloading a shared module; reload
        # would overwrite pytest's patched attributes and leak mocks to peers.
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(diagnostics))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            self.assertFalse(
                any(isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "load_catalog"
                    for child in ast.walk(node))
            )

    def test_invalid_catalog_fails_before_any_status_log_or_systemd(self):
        with patch.object(diagnostics, "load_catalog",
                          side_effect=ValueError("catalog drifts")), \
             patch.object(diagnostics, "status",
                          side_effect=AssertionError("status read")) as status, \
             patch.object(diagnostics, "read_log",
                          side_effect=AssertionError("log read")) as logs, \
             patch.object(diagnostics, "_systemd",
                          side_effect=AssertionError("systemd read")) as systemd:
            with self.assertRaisesRegex(ValueError, "catalog drifts"):
                diagnostics.diagnose(directory=Path("/not-read"))
            status.assert_not_called()
            logs.assert_not_called()
            systemd.assert_not_called()

    def test_unknown_name_denied_before_side_effects(self):
        with patch.object(diagnostics, "status",
                          side_effect=AssertionError("status read")) as status, \
             patch.object(diagnostics, "read_log",
                          side_effect=AssertionError("log read")) as logs:
            with self.assertRaisesRegex(ValueError, "unknown deployment target"):
                diagnostics.diagnose("ocpp-simulator", directory=Path("/not-read"))
            status.assert_not_called()
            logs.assert_not_called()

    def test_checked_catalog_matches_legacy_registry(self):
        catalog = load_catalog()
        self.assertEqual(
            tuple((t.id, t.repository) for t in catalog.targets), TARGETS
        )
        self.assertEqual(len(catalog.targets), 8)


if __name__ == "__main__":
    unittest.main()
