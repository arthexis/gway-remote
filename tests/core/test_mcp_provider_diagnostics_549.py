"""Phase B read-only MCP provider doctor: no new runtime authority or writes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.cli.registry import build_parser
from gway_remote.mcp_provider_diagnostics import (
    check_provider, format_provider_check, load_watchtower_catalog,
)
from gway_remote.mcp_source_registry import SourceRegistration
from gway_remote.reconcile import TARGETS


READ = {"name": "lookup", "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True}}
WRITE = {"name": "update", "inputSchema": {"type": "object"}}


def registration(deployment=None):
    return SourceRegistration("fixture", "a" * 40, "/usr/bin/true",
                              ("/usr/bin/true",), "arthe", True,
                              deployment=deployment)


def discovered(registrations):
    return lambda directory: tuple(registrations)


def listed(registrations, *, node_id):
    return {"node": node_id, "providers": [{
        "provider": "fixture", "node": node_id, "revision": "a" * 40,
        "status": "available", "tools": [READ, WRITE],
    }]}


def snapshot(*, scope="gway:execute", node="gway-001"):
    return {"schema": 1, "count": 2, "tools": [
        {"name": "fixture__lookup", "node": node, "source": "fixture",
         "required_scope": "gway:read"},
        {"name": "fixture__update", "node": node, "source": "fixture",
         "required_scope": scope},
    ]}


class ProviderDoctorTests(unittest.TestCase):
    def test_cli_parser_requires_exact_explicit_provider_check(self):
        parser = build_parser(("system-health",), TARGETS)
        args = parser.parse_args(["mcp", "provider", "check", "fixture", "--json"])
        self.assertEqual((args.command, args.mcp_section, args.mcp_action,
                          args.source_id, args.json),
                         ("mcp", "provider", "check", "fixture", True))
        with self.assertRaises(SystemExit):
            parser.parse_args(["mcp", "provider"])
        with self.assertRaisesRegex(ValueError, "invalid_source_id"):
            check_provider("../secrets")

    def test_read_only_local_catalog_and_unknown_remote_proof(self):
        report = check_provider("fixture", node="gway-001",
                                discover=discovered([registration()]),
                                list_providers=listed)
        self.assertEqual(report["state"], "available")
        self.assertEqual(report["manifest"], {"state": "valid", "revision": "a" * 40})
        self.assertEqual(report["executable"]["state"], "validated_by_manifest_parser")
        self.assertEqual(report["watchtower"], {"state": "unknown", "evidence": "not_supplied"})
        self.assertEqual(report["installed_release"]["state"], "unverified")
        self.assertIsNone(report["installed_release"]["sha"])
        self.assertEqual(report["deployment"]["state"], "not_declared")
        self.assertEqual({x["name"]: x["required_scope"] for x in report["catalog"]["tools"]},
                         {"lookup": "gway:read", "update": "gway:execute"})
        self.assertNotIn("/usr/bin", json.dumps(report))
        self.assertIn("Installed release SHA: unverified", format_provider_check(report))

    def test_snapshot_matching_and_scope_or_node_drift(self):
        def check(value):
            return check_provider("fixture", node="gway-001",
                                  watchtower_catalog=value,
                                  discover=discovered([registration()]),
                                  list_providers=listed)
        match = check(snapshot())
        self.assertEqual(match["watchtower"]["state"], "matches_snapshot")
        self.assertEqual(match["watchtower"]["evidence"], "caller_supplied_unverified")
        for bad in (snapshot(scope="gway:read"), snapshot(node="gway-002")):
            report = check(bad)
            self.assertEqual(report["code"], "catalog_snapshot_mismatch")
            self.assertEqual(report["watchtower"]["state"], "differs_snapshot")
            self.assertEqual(report["state"], "available")

    def test_registry_fails_closed_without_leaking_manifest_content(self):
        for fail in (ValueError("TOKEN=secret"), PermissionError("private-path")):
            with self.subTest(type=type(fail)), patch(
                "gway_remote.mcp_provider_diagnostics.provider_list") as invoked:
                def broken(_):
                    raise fail
                report = check_provider("fixture", node="gway-001", discover=broken)
                self.assertEqual(report["code"], "registry_invalid_or_unreadable")
                self.assertNotIn("secret", json.dumps(report))
                self.assertNotIn("private-path", json.dumps(report))
                invoked.assert_not_called()
        missing = check_provider("fixture", node="gway-001", discover=discovered([]))
        self.assertEqual(missing["code"], "provider_not_installed")

    def test_provider_outage_preserves_read_only_fail_closed_state(self):
        def unavailable(registrations, *, node_id):
            return {"providers": [{"provider": "fixture", "status": "unavailable",
                                   "error": {"code": "some-secret"}, "tools": []}]}
        report = check_provider("fixture", node="gway-001",
                                discover=discovered([registration()]),
                                list_providers=unavailable)
        self.assertEqual(report["code"], "provider_discovery_unavailable")
        self.assertEqual(report["catalog"]["state"], "unavailable")
        self.assertNotIn("some-secret", json.dumps(report))

    def test_historical_deployment_receipt_never_claims_current_release(self):
        deployment = {"schema": 1, "revision": "b" * 40, "checkout": "/opt/app",
                      "runner": "/opt/app/deploy.sh"}
        calls = []
        def receipt(app, *, resolve):
            calls.append((app, resolve(app)["revision"]))
            return {"state": "succeeded", "application": app}
        report = check_provider("fixture", node="gway-001",
                                discover=discovered([registration(deployment)]),
                                list_providers=listed, receipt_reader=receipt)
        self.assertEqual(calls, [("fixture", "b" * 40)])
        self.assertEqual(report["receipt"], {"state": "succeeded",
                                             "evidence": "historical_only"})
        self.assertIsNone(report["installed_release"]["sha"])

    def test_snapshot_is_bounded_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            path.write_text(json.dumps(snapshot()))
            self.assertEqual(load_watchtower_catalog(path)["count"], 2)
            symlink = Path(temp) / "catalog-link.json"
            symlink.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "invalid_catalog_file"):
                load_watchtower_catalog(symlink)
            for bad in ({"schema": 1, "count": 1, "tools": []},
                        {"schema": True, "count": 0, "tools": []},
                        {"schema": 1, "count": True, "tools": [{}]}):
                path.write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError, "invalid_catalog_schema"):
                    load_watchtower_catalog(path)
            fifo = Path(temp) / "catalog.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "invalid_catalog_file"):
                load_watchtower_catalog(fifo)
            path.write_bytes(b"x" * 262145)
            with self.assertRaisesRegex(ValueError, "invalid_catalog_file"):
                load_watchtower_catalog(path)

    def test_no_installation_or_tool_call_in_diagnosis(self):
        with patch("gway_remote.mcp_node_providers.provider_call") as invocation:
            report = check_provider("fixture", node="gway-001",
                                    discover=discovered([registration()]),
                                    list_providers=listed)
        self.assertEqual(report["catalog"]["state"], "available")
        invocation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
