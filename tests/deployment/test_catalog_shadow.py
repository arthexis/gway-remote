"""P1 hermetic contract: metadata-only catalog, never a deployment gate."""
import copy
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipapp

from gway_remote.catalog_shadow import (
    Catalog, SCHEMA, check_shadow_parity, load_catalog, parse_catalog,
)
from gway_remote.reconcile import TARGETS
from gway_remote.target_export import export_targets

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "gway_remote" / "data" / "appliance-targets.v1.json"
EXPECTED = (
    "ocpp-csms", "ocpp-reports", "gway-lcd-sound", "gway-agent-ops",
    "gway-ap-kiosk", "gway-rfid", "gway-bastion",
)
# Golden byte representation from the pre-P1 public schema=1 export.
# SHA-1 here is a content fingerprint, not a signature or deploy revision.
GOLDEN_EXPORT = (
    '{"revision":"f602ee0234e4232246c67aa8cd02bd52fc4bff8b",'
    '"schema":1,"targets":['
    '{"name":"ocpp-csms","repository":"arthexis/ocpp-csms"},'
    '{"name":"ocpp-reports","repository":"arthexis/ocpp-reports"},'
    '{"name":"gway-lcd-sound","repository":"arthexis/gway-lcd-sound"},'
    '{"name":"gway-agent-ops","repository":"arthexis/gway-agent-ops"},'
    '{"name":"gway-ap-kiosk","repository":"arthexis/gway-ap-kiosk"},'
    '{"name":"gway-rfid","repository":"arthexis/gway-rfid"},'
    '{"name":"gway-bastion","repository":"arthexis/gway-bastion"}]}'
)


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class ShadowCatalogTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.payload = json.loads(self.source)

    def mutate(self, edit):
        payload = copy.deepcopy(self.payload)
        edit(payload)
        return compact(payload)

    def test_exact_seven_targets_order_adapters_probes_and_modes(self):
        catalog = load_catalog()
        self.assertIsInstance(catalog, Catalog)
        self.assertEqual(catalog.schema, SCHEMA)
        self.assertEqual(tuple(item.id for item in catalog.targets), EXPECTED)
        self.assertEqual(tuple((item.id, item.repository) for item in catalog.targets), TARGETS)
        self.assertEqual(catalog.targets[-1].adapter_id, "deploy_bastion")
        self.assertEqual(catalog.targets[-1].probe_id, None)
        self.assertEqual(catalog.targets[-1].release_mode, "stage_only")
        self.assertTrue(all(t.release_mode == "standard" for t in catalog.targets[:-1]))
        self.assertEqual(check_shadow_parity(catalog), catalog)
        with self.assertRaises(FrozenInstanceError):
            catalog.targets[-1].id = "changed"

    def test_repeated_load_is_pure_and_idempotent(self):
        before = SOURCE.read_bytes()
        with patch("subprocess.run", side_effect=AssertionError("no commands")):
            left = load_catalog()
            right = load_catalog()
        self.assertEqual(left, right)
        self.assertEqual(SOURCE.read_bytes(), before)

    def test_public_target_export_is_byte_identical_and_independent(self):
        before = compact(export_targets())
        self.assertEqual(before, GOLDEN_EXPORT)
        self.assertEqual(export_targets()["schema"], 1)
        self.assertEqual(len(export_targets()["revision"]), 40)
        self.assertEqual(tuple(t.id for t in load_catalog().targets), EXPECTED)
        self.assertEqual(compact(export_targets()), before)

    def test_invalid_or_duplicate_json_properties_fail_closed(self):
        duplicate_root = (
            '{"schema":"gway-remote/appliance-catalog/v1",'
            '"schema":"gway-remote/appliance-catalog/v1","targets":[]}'
        )
        duplicate_nested = self.source.replace(
            '"id": "ocpp-csms",',
            '"id": "ocpp-csms", "id": "ocpp-csms",', 1
        )
        self.assertNotEqual(self.source, duplicate_nested)
        for source in (
            duplicate_root, duplicate_nested, "{", "null", "[]", "true",
            '{"schema":NaN,"targets":[]}', self.source + "garbage",
        ):
            with self.subTest(source=source[:75]):
                with self.assertRaises(ValueError):
                    parse_catalog(source)
        with self.assertRaises(ValueError):
            parse_catalog(self.source + " " * 32768)
        with self.assertRaises(ValueError):
            parse_catalog(self.source.encode("utf-8"))

    def test_unknown_fields_privileged_data_and_schema_rejected(self):
        fixtures = (
            lambda x: x.update(schema=2),
            lambda x: x.update(schema="target_export/v1"),
            lambda x: x.update(approved_nodes=["gway-001"]),
            lambda x: x["targets"][0].update(shell="sh deploy.sh"),
            lambda x: x["targets"][0].update(argv=["sh", "./deploy.sh"]),
            lambda x: x["targets"][0].update(enabled=True),
            lambda x: x["targets"][0].update(permissions=["gway:execute"]),
            lambda x: x["targets"][0].update(revision="a" * 40),
            lambda x: x["targets"][0].update(installed=True),
            lambda x: x["targets"][0].pop("adapter_id"),
            lambda x: x.update(targets=[]),
        )
        for mutate in fixtures:
            with self.subTest(mutate=str(mutate)):
                with self.assertRaises(ValueError):
                    parse_catalog(self.mutate(mutate))

    def test_invalid_reserved_duplicate_and_colliding_ids(self):
        for name in ("all", "admission", "report", "deploy", "foo_bar",
                     "Foo-Bar", "ocpp--csms", "../gway-rfid", "gway-rfid/",
                     "gway-bastion ", "foo.bar"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    parse_catalog(self.mutate(
                        lambda x: x["targets"][0].update(id=name)
                    ))
        for mutate in (
            lambda x: x["targets"][1].update(id=x["targets"][0]["id"],
                                             repository=x["targets"][0]["repository"]),
            lambda x: x["targets"][1].update(repository=x["targets"][0]["repository"]),
            # The normalized job ID would collide if snake_case were admitted.
            lambda x: (
                x["targets"][0].update(id="foo-bar", repository="arthexis/foo-bar"),
                x["targets"][1].update(id="foo_bar", repository="arthexis/foo_bar"),
            ),
        ):
            with self.subTest(mutate=str(mutate)):
                with self.assertRaises(ValueError):
                    parse_catalog(self.mutate(mutate))

    def test_untrusted_repository_adapter_probe_and_modes_rejected(self):
        bad = (
            lambda x: x["targets"][0].update(repository="another/ocpp-csms"),
            lambda x: x["targets"][0].update(repository="arthexis/other"),
            lambda x: x["targets"][0].update(adapter_id="__import__('os')"),
            lambda x: x["targets"][0].update(probe_id="/tmp/probe.py"),
            lambda x: x["targets"][0].update(release_mode="root"),
            lambda x: x["targets"][0].update(release_mode="stage_only"),
            lambda x: x["targets"][-1].update(release_mode="standard"),
            lambda x: x["targets"][0].update(probe_id=None),
            lambda x: x["targets"][-1].update(probe_id="gway-bastion"),
        )
        for edit in bad:
            with self.subTest(edit=str(edit)):
                with self.assertRaises(ValueError):
                    parse_catalog(self.mutate(edit))

    def test_drift_in_order_adapter_and_probe_is_not_admitted(self):
        def flip_order(x):
            x["targets"][0], x["targets"][1] = x["targets"][1], x["targets"][0]

        fixtures = (
            flip_order,
            lambda x: x["targets"][0].update(adapter_id="deploy_other"),
            lambda x: x["targets"][0].update(probe_id="gway-rfid"),
            lambda x: x["targets"][0].update(repository="arthexis/different"),
        )
        for edit in fixtures:
            with self.subTest(edit=str(edit)):
                try:
                    changed = parse_catalog(self.mutate(edit))
                except ValueError:
                    continue
                with self.assertRaises(ValueError):
                    check_shadow_parity(changed)

        from gway_remote import best_effort, probe_registry
        good = load_catalog()
        with patch.dict(best_effort.INSTALLERS, {"ocpp-csms": "unreviewed"}, clear=False):
            with self.assertRaises(ValueError):
                check_shadow_parity(good)
        with patch.dict(probe_registry.PROBES, {"ocpp-csms": probe_registry.Probe()}, clear=False):
            with self.assertRaises(ValueError):
                check_shadow_parity(good)
        self.assertEqual(load_catalog(), good)

    def test_missing_resource_fails_closed_without_fallback(self):
        original = compact(export_targets())
        with patch("gway_remote.catalog_shadow.resources.files",
                   side_effect=FileNotFoundError("missing")):
            with self.assertRaisesRegex(ValueError, "resource unavailable"):
                load_catalog()
        self.assertEqual(compact(export_targets()), original)

    def test_packaged_and_zipapp_resource_in_isolated_subprocess(self):
        """No network, no checkout-dependent paths and no CLI deployment."""
        program = (
            "import json\n"
            "from gway_remote.catalog_shadow import load_catalog\n"
            "from gway_remote.target_export import export_targets\n"
            "print(json.dumps({'names':[t.id for t in load_catalog().targets],"
            "'export':export_targets()}, sort_keys=True, separators=(',',':')))\n"
        )
        with tempfile.TemporaryDirectory(prefix="p1-shadow-offline-") as tmp:
            tmp = Path(tmp)
            root = tmp / "installed"
            root.mkdir()
            shutil.copytree(
                ROOT / "gway_remote", root / "gway_remote",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            elsewhere = tmp / "outside-checkout"
            elsewhere.mkdir()
            env = os.environ.copy()
            env["PYTHONPATH"] = str(root)
            proc = subprocess.run(
                [sys.executable, "-c", program], cwd=elsewhere, env=env,
                capture_output=True, text=True, timeout=30, check=True
            )
            installed = json.loads(proc.stdout)
            self.assertEqual(installed["names"], list(EXPECTED))
            self.assertEqual(compact(installed["export"]), GOLDEN_EXPORT)

            # The actual CLI installer builds zipapps from the copied package.
            app = tmp / "zipapp-src"
            app.mkdir()
            shutil.copytree(root / "gway_remote", app / "gway_remote")
            (app / "__main__.py").write_text(program, encoding="utf-8")
            archive = tmp / "catalog-test.pyz"
            zipapp.create_archive(app, archive, interpreter="/usr/bin/env python3")
            env.pop("PYTHONPATH", None)
            proc = subprocess.run(
                [sys.executable, "-I", str(archive)], cwd=elsewhere, env=env,
                capture_output=True, text=True, timeout=30, check=True
            )
            packaged = json.loads(proc.stdout)
            self.assertEqual(packaged, installed)
            self.assertEqual(compact(export_targets()), GOLDEN_EXPORT)

    def test_legacy_consumers_do_not_import_shadow_catalog(self):
        # Future P3 will explicitly migrate consumers. P1 must not.
        for relative in (
            "gway_remote/reconcile.py", "gway_remote/target_export.py",
            "gway_remote/deploy_dispatch.py", "gway_remote/best_effort.py",
            "gway_remote/cli/deploy.py", "gway_remote/deploy_failure_issues.py",
        ):
            with self.subTest(relative=relative):
                self.assertNotIn("catalog_shadow", (ROOT / relative).read_text())


if __name__ == "__main__":
    unittest.main()
