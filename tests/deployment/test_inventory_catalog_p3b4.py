"""P3-B4: hermetic inventory read-side catalog migration, no policy changes."""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gway_remote import deployments
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


SHA = "a" * 40
OTHER = "b" * 40
CHECKED_AT = "2026-11-17T00:00:00+00:00"


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 17, 0, 0, 0, tzinfo=timezone.utc)


class DeploymentCatalogP3B4Tests(unittest.TestCase):
    def _inventory(self, *, node="gway-001", hostname="gway-001",
                   repository=None, policy=(), installed=None, attempts=None,
                   catalog=None, bastion=None):
        checked = load_catalog() if catalog is None else catalog
        with patch.object(deployments, "load_catalog", return_value=checked) as loader, \
             patch.object(deployments.socket, "gethostname", return_value=hostname), \
             patch.object(deployments, "main_head", return_value=SHA) as github, \
             patch.object(deployments, "read_bastion_evidence", return_value=bastion or {
                 "activated_sha": None, "release_state": "staged", "staged_sha": OTHER,
                 "evidence": "verified", "runtime": "not_applicable"
             }) as bastion_read, \
             patch.object(deployments, "datetime", FrozenDatetime):
            report = deployments.inventory(
                repository, node=node, policy=policy, client=object(),
                attempts={} if attempts is None else attempts,
                installed=(lambda name: installed.get(name)) if installed is not None else (lambda _: None),
            )
            return report, deployments.format_inventory(report), loader.call_count, github.call_count, bastion_read.call_count

    def test_exact_order_and_known_source_mapping_no_rights_from_catalog(self):
        report, output, loads, gh, bastion = self._inventory()
        self.assertEqual(loads, 1)
        self.assertEqual(gh, 8)
        self.assertEqual(bastion, 1)
        self.assertEqual(report["checked_at"], CHECKED_AT)
        self.assertTrue(report["local_evidence"])
        self.assertEqual(
            [(r["name"], r["repository"]) for r in report["components"]], list(TARGETS))
        self.assertEqual([r["managed"] for r in report["components"]], [False] * 8)
        self.assertEqual([r["deployable"] for r in report["components"]], [False] * 8)
        self.assertTrue(all(r["management_reason"] == "not managed"
                            for r in report["components"]))
        self.assertTrue(all(r["revision_status"] == "unknown"
                            for r in report["components"]))
        self.assertTrue(all(r["latest_sha"] == SHA for r in report["components"]))
        self.assertIn("Deployment inventory for gway-001", output)
        self.assertIn("Unknown installation is unverified", output)

    def test_gway001_only_uses_independent_allowlist(self):
        report, _, loads, gh, bastion = self._inventory(
            repository="ocpp-csms", policy={"ocpp-csms"},
            installed={"ocpp-csms": SHA[:12]})
        row = report["components"][0]
        self.assertEqual((loads, gh, bastion), (1, 1, 0))
        self.assertEqual((row["managed"], row["deployable"]), (True, True))
        self.assertEqual(row["management_reason"], "approved for local deployment")
        self.assertEqual(row["revision_status"], "current")
        remote, out, loads2, gh2, bastion2 = self._inventory(
            node="gway-004", repository="ocpp-csms", policy={"ocpp-csms"},
            installed={"ocpp-csms": SHA[:12]})
        row2 = remote["components"][0]
        self.assertEqual((loads2, gh2, bastion2), (1, 1, 0))
        self.assertEqual((row2["managed"], row2["deployable"]), (True, False))
        self.assertEqual(row2["management_reason"], "remote execution not enabled")
        self.assertFalse(remote["local_evidence"])
        self.assertIsNone(row2["installed_sha"])
        self.assertEqual(row2["revision_status"], "unknown")
        self.assertIn("remote node; local evidence not used", deployments.format_inventory(
            self._inventory(node="gway-004", repository="gway-bastion",
                            policy={"gway-bastion"})[0]))

    def test_other_local_node_never_deployable(self):
        report, _, _, _, _ = self._inventory(
            node="gway-004", hostname="gway-004",
            repository="ocpp-csms", policy={"ocpp-csms"})
        row = report["components"][0]
        self.assertTrue(row["managed"])
        self.assertFalse(row["deployable"])
        self.assertEqual(row["management_reason"], "only gway-001 can apply")

    def test_attempt_does_not_prove_installation_and_bastion_staging(self):
        attempts = {"gway-bastion": {"sha": SHA, "status": "installed",
                                     "at": "2026-11-17T00:00:00+00:00"}}
        report, output, _, _, bastion = self._inventory(
            repository="gway-bastion", policy={"gway-bastion"}, attempts=attempts)
        row = report["components"][0]
        self.assertEqual(bastion, 1)
        self.assertEqual(row["attempt_status"], "installed")
        self.assertEqual(row["attempted_sha"], SHA)
        self.assertIsNone(row["installed_sha"])
        self.assertEqual(row["revision_status"], "unknown")
        self.assertEqual(row["release_state"], "staged")
        self.assertFalse("Activated/installed SHA:" in output)

    def test_unknown_repository_rejected_before_policy_and_github_io(self):
        with patch.object(deployments, "_node_policy",
                          side_effect=AssertionError("policy read")) as policy, \
             patch.object(deployments, "main_head",
                          side_effect=AssertionError("github read")) as github:
            with self.assertRaisesRegex(ValueError, "Unknown repository"):
                deployments.inventory("ocpp-simulator", node="gway-001")
            policy.assert_not_called()
            github.assert_not_called()

    def test_corrupt_catalog_fails_before_node_policy_and_network(self):
        with patch.object(deployments, "load_catalog",
                          side_effect=ValueError("catalog mismatch")) as loader, \
             patch.object(deployments.socket, "gethostname",
                          side_effect=AssertionError("host read")) as host, \
             patch.object(deployments, "main_head",
                          side_effect=AssertionError("github read")) as github, \
             patch.object(deployments, "_node_policy",
                          side_effect=AssertionError("policy read")) as policy:
            with self.assertRaisesRegex(ValueError, "catalog mismatch"):
                deployments.inventory()
            loader.assert_called_once_with()
            host.assert_not_called()
            policy.assert_not_called()
            github.assert_not_called()

    def test_missing_policy_still_fails_closed(self):
        with patch.object(deployments, "_node_policy",
                          side_effect=RuntimeError("Ansible inventory unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Ansible inventory unavailable"):
                deployments.inventory(node="gway-001", attempts={}, client=object())

    def test_no_eager_catalog_load_at_import(self):
        tree = ast.parse(inspect.getsource(deployments))
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            self.assertFalse(any(
                isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                and child.func.id == "load_catalog"
                for child in ast.walk(stmt)
            ))

    def test_checked_catalog_parity_with_eight_reviewed_sources(self):
        self.assertEqual(
            tuple((t.id, t.repository) for t in load_catalog().targets), TARGETS)


if __name__ == "__main__":
    unittest.main()
