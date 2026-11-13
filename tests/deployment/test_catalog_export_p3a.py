"""P3-A offline acceptance: pure catalog resource reader and checked v1 export.

No node connection, deployment execution, workflow dispatch, runtime mutation,
Ansible, MCP provisioning or real remote GitHub requests.
"""
from __future__ import annotations

import hashlib
import importlib
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

from gway_remote import best_effort, catalog_shadow, probe_registry, reconcile
from gway_remote.target_export import export_targets

ROOT = Path(__file__).resolve().parents[2]
REVISION = "f602ee0234e4232246c67aa8cd02bd52fc4bff8b"
LEGACY = (
    ("ocpp-csms", "arthexis/ocpp-csms"),
    ("ocpp-reports", "arthexis/ocpp-reports"),
    ("gway-lcd-sound", "arthexis/gway-lcd-sound"),
    ("gway-agent-ops", "arthexis/gway-agent-ops"),
    ("gway-ap-kiosk", "arthexis/gway-ap-kiosk"),
    ("gway-rfid", "arthexis/gway-rfid"),
    ("gway-bastion", "arthexis/gway-bastion"),
)
GOLDEN = (
    b'{"revision":"f602ee0234e4232246c67aa8cd02bd52fc4bff8b",'
    b'"schema":1,"targets":['
    b'{"name":"ocpp-csms","repository":"arthexis/ocpp-csms"},'
    b'{"name":"ocpp-reports","repository":"arthexis/ocpp-reports"},'
    b'{"name":"gway-lcd-sound","repository":"arthexis/gway-lcd-sound"},'
    b'{"name":"gway-agent-ops","repository":"arthexis/gway-agent-ops"},'
    b'{"name":"gway-ap-kiosk","repository":"arthexis/gway-ap-kiosk"},'
    b'{"name":"gway-rfid","repository":"arthexis/gway-rfid"},'
    b'{"name":"gway-bastion","repository":"arthexis/gway-bastion"}]}'
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def legacy_export():
    """Independent, pre-P3 export algorithm, used ONLY to prove rollback parity."""
    targets = [{"name": name, "repository": repository} for name, repository in LEGACY]
    digest = hashlib.sha1(canonical(targets)).hexdigest()
    return {"schema": 1, "revision": digest, "targets": targets}


class FakeResource:
    def __init__(self, content):
        self.content = content

    def joinpath(self, *parts):
        if parts != ("data", "appliance-targets.v1.json"):
            raise AssertionError("unexpected resource path")
        return self

    def read_text(self, *, encoding):
        if encoding != "utf-8":
            raise AssertionError("unexpected encoding")
        return self.content


class CatalogExportP3ATests(unittest.TestCase):
    def test_public_export_is_byte_for_byte_golden(self):
        actual = export_targets()
        self.assertEqual(actual["schema"], 1)
        self.assertEqual(actual["revision"], REVISION)
        self.assertEqual(canonical(actual), GOLDEN)
        self.assertEqual(canonical(actual), canonical(legacy_export()))
        self.assertEqual(tuple((x.id, x.repository)
                               for x in catalog_shadow.load_catalog_data().targets), LEGACY)
        self.assertEqual(reconcile.TARGETS, LEGACY)
        self.assertEqual(canonical(export_targets()), GOLDEN)

    def test_pure_loader_does_not_consult_registries(self):
        with patch.object(catalog_shadow, "check_shadow_parity",
                          side_effect=AssertionError("pure loader called parity")):
            pure = catalog_shadow.load_catalog_data()
        self.assertEqual(tuple(x.id for x in pure.targets),
                         tuple(name for name, _ in LEGACY))
        self.assertEqual(pure.targets[-1].release_mode, "stage_only")
        self.assertIsNone(pure.targets[-1].probe_id)
        self.assertEqual(catalog_shadow.load_catalog(), pure)

    def test_checked_export_rejects_unreviewed_adapter_and_probe_drift(self):
        original = canonical(export_targets())
        with patch.dict(best_effort.INSTALLERS, {"ocpp-csms": "deploy_other"}):
            with self.assertRaisesRegex(ValueError, "adapter mismatch"):
                export_targets()
        with patch.dict(probe_registry.PROBES,
                        {"ocpp-csms": probe_registry.Probe()}):
            with self.assertRaisesRegex(ValueError, "unknown kind"):
                export_targets()
        with patch("gway_remote.reconcile.TARGETS",
                   (LEGACY[1], LEGACY[0], *LEGACY[2:])):
            with self.assertRaisesRegex(ValueError, "ordered"):
                export_targets()
        self.assertEqual(canonical(export_targets()), original)

    def test_adapter_is_not_executed_by_export(self):
        from gway_remote import __main__ as handlers
        with patch.object(handlers, "deploy_csms",
                          side_effect=AssertionError("installer invoked")), \
             patch("subprocess.run", side_effect=AssertionError("subprocess invoked")), \
             patch("pathlib.Path.write_bytes", side_effect=AssertionError("write invoked")), \
             patch("pathlib.Path.write_text", side_effect=AssertionError("write invoked")):
            # Parity checks only callability, never invoke a handler or subprocess.
            self.assertEqual(canonical(export_targets()), GOLDEN)

    def test_missing_resource_rejected_without_legacy_fallback(self):
        with patch.object(catalog_shadow.resources, "files",
                          side_effect=FileNotFoundError("absent")):
            for call in (catalog_shadow.load_catalog_data,
                         catalog_shadow.load_catalog, export_targets):
                with self.subTest(call=call.__name__):
                    with self.assertRaisesRegex(ValueError, "resource unavailable"):
                        call()
        self.assertEqual(canonical(export_targets()), GOLDEN)

    def test_corrupt_duplicate_unexpected_properties_fail_closed(self):
        original = (ROOT / "gway_remote/data/appliance-targets.v1.json").read_text()
        bad = (
            "{", "null",
            '{"schema":"gway-remote/appliance-catalog/v1",'
            '"schema":"gway-remote/appliance-catalog/v1","targets":[]}',
            original.replace('"id": "ocpp-csms",',
                             '"id": "ocpp-csms", "id": "ocpp-csms",', 1),
            original.replace("gway-remote/appliance-catalog/v1", "other/v1", 1),
            original.replace('"adapter_id": "deploy_csms"', '"adapter_id": "__import__"', 1),
            original.replace('"release_mode": "stage_only"',
                             '"release_mode": "standard"', 1),
        )
        for source in bad:
            with self.subTest(source=source[:40]), \
                 patch.object(catalog_shadow.resources, "files",
                              return_value=FakeResource(source)):
                with self.assertRaises(ValueError):
                    catalog_shadow.load_catalog_data()
                with self.assertRaises(ValueError):
                    export_targets()
        self.assertEqual(canonical(export_targets()), GOLDEN)

    def test_syntactically_valid_adapter_and_probe_mutations_fail_parity(self):
        original = (ROOT / "gway_remote/data/appliance-targets.v1.json").read_text()
        cases = (
            ('"adapter_id": "deploy_csms"', '"adapter_id": "deploy_bastion"'),
            ('"probe_id": "ocpp-csms"', '"probe_id": "gway-rfid"'),
        )
        for before, after in cases:
            self.assertIn(before, original)
            with self.subTest(before=before), patch.object(
                catalog_shadow.resources, "files",
                return_value=FakeResource(original.replace(before, after, 1))
            ):
                data = catalog_shadow.load_catalog_data()
                self.assertEqual(len(data.targets), 7)
                with self.assertRaises(ValueError):
                    export_targets()

    def test_explicit_rollback_equivalence_without_runtime_state(self):
        # The old algorithm and the P3-A checked reader share EXACT public
        # bytes. A code-only revert needs no journal, inventory or DB migration.
        previous = canonical(legacy_export())
        current = canonical(export_targets())
        self.assertEqual(previous, current)
        self.assertEqual(current, GOLDEN)
        self.assertEqual(hashlib.sha1(canonical(legacy_export()["targets"]))
                         .hexdigest(), REVISION)

    def test_import_orders_in_isolated_python_processes_and_zipapp(self):
        script = (
            "import importlib,json,sys\n"
            "mods=sys.argv[1].split(',')\n"
            "for index,name in enumerate(mods):\n"
            "    importlib.import_module('gway_remote.'+name)\n"
            "    if index == 0 and name == 'target_export':\n"
            "        assert 'gway_remote.reconcile' not in sys.modules\n"
            "from gway_remote.target_export import export_targets\n"
            "print(json.dumps(export_targets(),sort_keys=True,separators=(',',':')))\n"
        )
        orders = (
            "target_export,catalog_shadow,reconcile",
            "reconcile,target_export,catalog_shadow",
            "catalog_shadow,target_export,reconcile",
            "appliance_workflow_generator,target_export,reconcile",
        )
        with tempfile.TemporaryDirectory(prefix="p3a-offline-") as tmp:
            root = Path(tmp)
            installed = root / "installed"
            installed.mkdir()
            shutil.copytree(
                ROOT / "gway_remote", installed / "gway_remote",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            outside = root / "outside-repository"
            outside.mkdir()
            env = os.environ.copy()
            env["PYTHONPATH"] = str(installed)
            for order in orders:
                with self.subTest(order=order):
                    result = subprocess.run(
                        [sys.executable, "-c", script, order], env=env,
                        cwd=outside, capture_output=True, text=True,
                        timeout=30, check=True
                    )
                    self.assertEqual(result.stdout.strip().encode(), GOLDEN)

            ziproot = root / "zip-source"
            ziproot.mkdir()
            shutil.copytree(installed / "gway_remote", ziproot / "gway_remote")
            (ziproot / "__main__.py").write_text(
                script.replace("sys.argv[1].split(',')",
                               "['target_export','catalog_shadow','reconcile']"),
                encoding="utf-8"
            )
            archive = root / "p3a-test.pyz"
            zipapp.create_archive(ziproot, archive, interpreter="/usr/bin/env python3")
            env.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, "-I", str(archive)], env=env, cwd=outside,
                capture_output=True, text=True, timeout=30, check=True
            )
            self.assertEqual(result.stdout.strip().encode(), GOLDEN)


if __name__ == "__main__":
    unittest.main()
