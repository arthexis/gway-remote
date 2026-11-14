"""P3-B1: status catalog enumeration only; hermetic, no node or deploy access."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import importlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipapp

from gway_remote import catalog_shadow
from gway_remote import status as status_module
from gway_remote.reconcile import TARGETS
from gway_remote.target_export import export_targets

ROOT = Path(__file__).resolve().parents[2]
RESOURCE = ROOT / "gway_remote" / "data" / "appliance-targets.v1.json"
KNOWN = (
    "ocpp-csms", "ocpp-reports", "gway-lcd-sound", "gway-agent-ops",
    "gway-ap-kiosk", "gway-rfid", "gway-bastion",
)
REVISION = "f602ee0234e4232246c67aa8cd02bd52fc4bff8b"
STAGED = "c" * 40
ATTEMPTS = {
    "ocpp-csms": {"status": "installed", "sha": "a" * 40,
                  "at": "2026-11-13T10:00:00+00:00", "log": None},
    "ocpp-reports": {"status": "failed", "sha": "d" * 40,
                     "at": "2026-11-13T10:10:00+00:00", "log": None},
    "gway-bastion": {"status": "installed", "sha": STAGED,
                      "at": "2026-11-13T10:20:00+00:00", "log": None},
}


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)


class FixtureResource:
    def __init__(self, data):
        self.data = data

    def joinpath(self, *parts):
        if parts != ("data", "appliance-targets.v1.json"):
            raise AssertionError("non-reviewed catalog resource")
        return self

    def read_text(self, *, encoding):
        if encoding != "utf-8":
            raise AssertionError("noncanonical catalog encoding")
        return self.data


class StatusCatalogP3B1Tests(unittest.TestCase):
    def _snapshot(self, depth="deep", *, old_order=False):
        # Fully isolated evidence fixture; no live journal, probe, host or CLI.
        deep_calls, quick_calls = [], []
        legacy = SimpleNamespace(targets=tuple(
            SimpleNamespace(id=name) for name, _ in TARGETS))
        with ExitStack() as stack:
            load = stack.enter_context(patch.object(
                status_module, "load_catalog",
                return_value=legacy if old_order else None,
            )) if old_order else stack.enter_context(
                patch.object(status_module, "load_catalog",
                             wraps=status_module.load_catalog))
            stack.enter_context(patch.object(
                status_module, "read_attempts", return_value=ATTEMPTS))
            stack.enter_context(patch.object(
                status_module, "installed_revision",
                side_effect=lambda name: "b" * 12 if name == "ocpp-csms" else None))
            stack.enter_context(patch.object(
                status_module, "read_bastion_evidence", return_value={
                    "release_state": "staged", "staged_sha": STAGED,
                    "activated_sha": None, "runtime": "not_applicable",
                    "evidence": "verified",
                }))
            stack.enter_context(patch.object(
                status_module, "quick_component_check",
                side_effect=lambda name: quick_calls.append(name) or "service-active"))
            stack.enter_context(patch.object(
                status_module, "kiosk_activation_evidence", return_value=False))
            stack.enter_context(patch.object(
                status_module, "activated_timestamp", return_value=None))
            stack.enter_context(patch.object(
                status_module, "power_probe", return_value={"status": "unavailable"}))
            stack.enter_context(patch.object(
                status_module, "watchdog_inspect",
                return_value={"status": "unavailable", "devices": []}))
            stack.enter_context(patch.object(
                status_module.platform, "node", return_value="gway-001"))
            stack.enter_context(patch.object(status_module, "datetime", FrozenDatetime))
            stack.enter_context(patch.object(
                status_module, "perf_counter_ns",
                side_effect=itertools.count(0, 1_000_000)))
            # No host probe execution in this fixture.
            def probe(name):
                deep_calls.append(name)
                return False if name == "ocpp-reports" else True

            result = status_module.status(
                directory=Path("/not-read"), depth=depth, probe=probe)
        return result, load.call_count, deep_calls, quick_calls

    def test_exact_legacy_snapshot_deep_and_quick(self):
        self.assertEqual(tuple(name for name, _ in TARGETS), KNOWN)
        for depth in ("deep", "quick"):
            with self.subTest(depth=depth):
                old, _, old_deep, old_quick = self._snapshot(depth, old_order=True)
                new, calls, deep, quick = self._snapshot(depth)
                self.assertEqual(calls, 1)
                self.assertEqual(new, old)  # includes schema, timestamps, evidence
                self.assertEqual(deep, old_deep)
                self.assertEqual(quick, old_quick)
                self.assertEqual([x["name"] for x in new["components"]], list(KNOWN))
                self.assertEqual(new["schema"], "gway-remote/status/v1")
                self.assertEqual(new["checked_at"], "2026-11-13T12:00:00+00:00")
                self.assertEqual(deep if depth == "deep" else quick, list(KNOWN))
                self.assertEqual(quick if depth == "deep" else deep, [])

    def test_attempt_is_not_independently_installed_or_healthy(self):
        for depth in ("deep", "quick"):
            with self.subTest(depth=depth):
                report, _, _, _ = self._snapshot(depth)
                entries = {x["name"]: x for x in report["components"]}
                csms = entries["ocpp-csms"]
                self.assertEqual(csms["installation"], "installed")
                self.assertEqual(csms["attempted_sha"], "a" * 40)
                self.assertEqual(csms["installed_sha"], "b" * 12)
                self.assertEqual(csms["deployment_evidence"]["source_revision"], None)
                reports = entries["ocpp-reports"]
                self.assertEqual(reports["installation"], "failed")
                self.assertIsNone(reports["installed_sha"])
                self.assertEqual(reports["deployment_evidence"]["installation_state"], "unknown")
                self.assertEqual(reports["health"], "unhealthy" if depth == "deep" else "unknown")

    def test_bastion_stage_only_never_claims_activation(self):
        for depth in ("deep", "quick"):
            report, _, _, _ = self._snapshot(depth)
            bastion = report["components"][-1]
            self.assertEqual(bastion["name"], "gway-bastion")
            self.assertEqual(bastion["staged_sha"], STAGED)
            self.assertIsNone(bastion["installed_sha"])
            self.assertEqual(bastion["release_state"], "staged")
            self.assertEqual(bastion["health"], "not_applicable")
            evidence = bastion["deployment_evidence"]
            self.assertEqual(evidence["installation_state"], "staged")
            self.assertIsNone(evidence["activated_revision"])
            self.assertEqual(evidence["runtime_state"], "not_applicable")

    def test_invalid_depth_rejected_before_catalog_lookup(self):
        with patch.object(status_module, "load_catalog",
                          side_effect=AssertionError("unexpected read")) as load:
            with self.assertRaisesRegex(ValueError, "invalid_status_depth"):
                status_module.status(depth="not-valid")
            load.assert_not_called()

    def test_missing_resource_fails_closed_before_journal_or_probe(self):
        with patch.object(catalog_shadow.resources, "files",
                          side_effect=FileNotFoundError("absent")), \
             patch.object(status_module, "read_attempts",
                          side_effect=AssertionError("journal consulted")) as journal, \
             patch.object(status_module, "quick_component_check",
                          side_effect=AssertionError("probe called")) as quick, \
             patch.object(status_module, "power_probe",
                          side_effect=AssertionError("power probe called")):
            with self.assertRaisesRegex(ValueError, "resource unavailable"):
                status_module.status(depth="quick")
            journal.assert_not_called()
            quick.assert_not_called()

    def test_invalid_duplicate_json_and_registry_drift_fail_closed(self):
        valid = RESOURCE.read_text(encoding="utf-8")
        bad = (
            "{",
            valid.replace('"id": "ocpp-csms",',
                          '"id": "ocpp-csms", "id": "ocpp-csms",', 1),
            valid.replace('"adapter_id": "deploy_csms"',
                          '"adapter_id": "deploy_bastion"', 1),
            valid.replace('"probe_id": "ocpp-csms"',
                          '"probe_id": "gway-rfid"', 1),
            valid.replace('"release_mode": "stage_only"',
                          '"release_mode": "standard"', 1),
        )
        for item in bad:
            with self.subTest(case=item[:60]), \
                 patch.object(catalog_shadow.resources, "files",
                              return_value=FixtureResource(item)), \
                 patch.object(status_module, "read_attempts",
                              side_effect=AssertionError("journal consulted")) as journal:
                with self.assertRaises(ValueError):
                    status_module.status(depth="deep", probe=lambda _: self.fail(
                        "metadata rejected after invoking probe"))
                journal.assert_not_called()

    def test_no_new_subprocess_writes_or_probe_side_effects(self):
        # Read-only status fixture: installed, health and kiosk implementations
        # stay separate and are stubbed. The new loader itself performs none.
        with patch("subprocess.run",
                   side_effect=AssertionError("unexpected subprocess")), \
             patch("pathlib.Path.write_text",
                   side_effect=AssertionError("unexpected file write")), \
             patch("pathlib.Path.write_bytes",
                   side_effect=AssertionError("unexpected file write")):
            report, calls, deep, _ = self._snapshot()
        self.assertEqual(calls, 1)
        self.assertEqual(deep, list(KNOWN))
        self.assertEqual(len(report["components"]), 7)

    def test_public_export_and_code_only_rollback_parity(self):
        # A revert to the old TARGETS enumeration yields the same status
        # snapshots; no schema, runtime, inventory, or DB migration is needed.
        before = self._snapshot(old_order=True)[0]
        after = self._snapshot()[0]
        self.assertEqual(before, after)
        export = export_targets()
        self.assertEqual(export["schema"], 1)
        self.assertEqual(export["revision"], REVISION)
        self.assertEqual(tuple((row["name"], row["repository"])
                               for row in export["targets"]), TARGETS)

    def test_import_order_and_zipapp_outside_checkout(self):
        script = (
            "import importlib,json,sys\n"
            "from unittest.mock import patch\n"
            "from gway_remote import catalog_shadow\n"
            "for module in sys.argv[1].split(','):\n"
            "    with patch.object(catalog_shadow.resources,'files',"
            "side_effect=AssertionError('catalog loaded at import time')):\n"
            "        importlib.import_module('gway_remote.'+module)\n"
            "from gway_remote import status as s\n"
            "with patch.object(s,'read_attempts',return_value={}),"
            "patch.object(s,'installed_revision',return_value=None),"
            "patch.object(s,'read_bastion_evidence',return_value={'release_state':'unknown',"
            "'activated_sha':None,'staged_sha':None,'runtime':'unknown','evidence':'missing'}),"
            "patch.object(s,'kiosk_activation_evidence',return_value=False),"
            "patch.object(s,'activated_timestamp',return_value=None),"
            "patch.object(s,'power_probe',return_value={}),"
            "patch.object(s,'watchdog_inspect',return_value={}):\n"
            "    report=s.status(probe=lambda name:None,depth='deep')\n"
            "print(json.dumps({'schema':report['schema'],"
            "'names':[x['name'] for x in report['components']]},"
            "sort_keys=True,separators=(',',':')))\n"
        )
        orders = (
            "status,catalog_shadow,__main__",
            "catalog_shadow,__main__,status",
            "__main__,status,catalog_shadow",
        )
        expected = {"schema": "gway-remote/status/v1", "names": list(KNOWN)}
        with tempfile.TemporaryDirectory(prefix="p3b1-offline-") as tmp:
            root = Path(tmp)
            installed = root / "installed"
            installed.mkdir()
            shutil.copytree(
                ROOT / "gway_remote", installed / "gway_remote",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            outside = root / "outside-checkout"
            outside.mkdir()
            env = os.environ.copy()
            env["PYTHONPATH"] = str(installed)
            for order in orders:
                with self.subTest(order=order):
                    result = subprocess.run(
                        [sys.executable, "-c", script, order],
                        env=env, cwd=outside, capture_output=True, text=True,
                        check=True, timeout=30,
                    )
                    self.assertEqual(json.loads(result.stdout), expected)
            app = root / "zipapp-src"
            app.mkdir()
            shutil.copytree(installed / "gway_remote", app / "gway_remote")
            (app / "__main__.py").write_text(script, encoding="utf-8")
            archive = root / "status-p3b1.pyz"
            zipapp.create_archive(app, archive, interpreter="/usr/bin/env python3")
            env.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, "-I", str(archive), orders[0]],
                cwd=outside, env=env, capture_output=True, text=True,
                check=True, timeout=30,
            )
            self.assertEqual(json.loads(result.stdout), expected)


if __name__ == "__main__":
    unittest.main()
