"""Offline phase-C node doctor regressions: authorization != health."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gway_remote.cli.registry import build_parser
from gway_remote import node_onboarding_doctor as doctor
from gway_remote.reconcile import TARGETS

PIN_SHA = "a" * 64
ADDRESS = "10.0.1.2"


def inventory(*, verified=True, eligible=True, reachable="reachable",
              registered=True, address=ADDRESS):
    row = {"node": "gway-002", "registered": registered,
           "registration_state": "active", "identity_verified": verified,
           "execute_eligible": eligible, "reachable": reachable, "address": address}
    return {"schema": 1, "nodes": [row]}


def validated_pin(node):
    assert node == "gway-002"
    return ({"state": "pin_validated_offline"},
            {"address": ADDRESS, "host_key_sha256": PIN_SHA})


def read_ledger(node, sha):
    assert (node, sha) == ("gway-002", PIN_SHA)
    return ({"state": "readable_checkpoint_only"},
            {"state": "historical_succeeded", "observed_at":
             "2026-11-10T18:00:00+00:00", "evidence": "private_ledger_checkpoint"})


def inspect(data=None, pin=validated_pin, ledger=read_ledger):
    return doctor.diagnose_node(
        "gway-002", inventory_loader=lambda: inventory() if data is None else data,
        pin_inspector=pin, ledger_inspector=ledger)


class NodeDoctorTests(unittest.TestCase):
    def test_parser_requires_explicit_node_doctor(self):
        args = build_parser(("system-health",), TARGETS).parse_args(
            ["node", "doctor", "gway-002", "--json"])
        self.assertEqual((args.command, args.node_action, args.node, args.json),
                         ("node", "doctor", "gway-002", True))
        with self.assertRaises(ValueError):
            doctor.diagnose_node("../etc/passwd")
        with self.assertRaises(ValueError):
            doctor.diagnose_node("bad/host")

    def test_eligible_with_historical_success_is_not_operational(self):
        report = inspect()
        self.assertEqual(report["enrollment"]["state"], "active")
        self.assertEqual(report["attestation"]["state"], "verified")
        self.assertEqual(report["reachability"]["state"], "reachable")
        self.assertEqual(report["eligibility"]["state"], "granted")
        self.assertEqual(report["pinned_ssh"]["state"], "pin_validated_offline")
        self.assertTrue(report["ready_for_operator_test"])
        self.assertEqual(report["terminal_result"]["state"], "historical_succeeded")
        self.assertEqual(report["operational"]["state"], "unverified")
        self.assertEqual(report["ansible_recipe"]["state"], "unknown")
        self.assertEqual(report["executor"]["state"], "unknown")
        self.assertEqual(report["systemd_bus"]["state"], "unknown")
        self.assertEqual(report["installed_release"], {"state": "unverified", "sha": None})
        self.assertNotIn("10.0.1.2", json.dumps(report))
        self.assertNotIn(PIN_SHA, json.dumps(report))
        self.assertNotIn("ready", report["operational"]["state"])

    def test_missing_attestation_grant_reachability_or_pin_denies_readiness(self):
        for changed in (
            {"verified": False}, {"eligible": False},
            {"reachable": "unknown"}, {"registered": False},
            {"address": "10.0.3.9"},
        ):
            with self.subTest(changed=changed):
                report = inspect(inventory(**changed))
                self.assertFalse(report["ready_for_operator_test"])
                self.assertEqual(report["operational"]["state"], "unverified")
        for state in ("unknown", "not_pinned", "binding_mismatch",
                      "invalid_configuration", "unsafe_configuration"):
            with self.subTest(state=state):
                report = inspect(pin=lambda node: ({"state": state}, None))
                self.assertFalse(report["ready_for_operator_test"])
                self.assertEqual(report["terminal_result"]["state"], "unknown")

    def test_not_registered_and_unavailable_snapshot_fail_closed(self):
        missing = doctor.diagnose_node(
            "gway-002", inventory_loader=lambda: {"nodes": []},
            pin_inspector=Mock(side_effect=AssertionError("never inspect pin")))
        self.assertEqual(missing["enrollment"]["state"], "not_registered")
        self.assertFalse(missing["ready_for_operator_test"])
        unavailable = doctor.diagnose_node(
            "gway-002", inventory_loader=Mock(side_effect=ValueError("SECRET")),
            pin_inspector=Mock(side_effect=AssertionError("no pin")))
        self.assertEqual(unavailable["enrollment"],
                         {"state": "unknown", "reason": "inventory_unavailable"})
        self.assertNotIn("SECRET", json.dumps(unavailable))

    def test_no_ssh_tokens_worker_bus_or_writes_during_inspection(self):
        with patch("gway_remote.watchtower_exec_transport.SSHTransport.invoke") as ssh, \
             patch("gway_remote.node_exec_protocol.serve_one") as worker, \
             patch("gway_remote.watchtower_exec_eligibility.set_eligibility") as grant:
            report = inspect()
        self.assertTrue(report["ready_for_operator_test"])
        ssh.assert_not_called()
        worker.assert_not_called()
        grant.assert_not_called()

    def test_private_pin_config_no_follow_and_pinned_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "execute.json"
            item = {"node": "gway-002", "address": ADDRESS, "ssh_host_alias": "gway-002",
                    "known_hosts": str(Path(temp) / "hosts"),
                    "identity_file": str(Path(temp) / "id"),
                    "host_key_sha256": PIN_SHA, "remote_user": "gway-relay"}
            path.write_text(json.dumps({"enabled": True, "nodes": [item]}))
            path.chmod(0o600)
            validate = Mock()
            result, binding = doctor._private_config(
                "gway-002", path=path, pinned_factory=validate,
                required_owner=os.geteuid())
            self.assertEqual(result["state"], "pin_validated_offline")
            self.assertEqual(binding, {
                "address": ADDRESS, "host_key_sha256": PIN_SHA,
                "configured_nodes": [{"node": "gway-002", "address": ADDRESS}],
            })
            validate.assert_called_once()
            path.chmod(0o666)
            invalid, _ = doctor._private_config(
                "gway-002", path=path, pinned_factory=validate,
                required_owner=os.geteuid())
            self.assertEqual(invalid["state"], "unsafe_configuration")
            path.chmod(0o600)
            link = Path(temp) / "alias.json"
            link.symlink_to(path)
            invalid, _ = doctor._private_config(
                "gway-002", path=link, pinned_factory=validate,
                required_owner=os.geteuid())
            self.assertNotEqual(invalid["state"], "pin_validated_offline")
            path.write_text(json.dumps({"enabled": True, "nodes": [item, item]}))
            invalid, _ = doctor._private_config(
                "gway-002", path=path, pinned_factory=validate,
                required_owner=os.geteuid())
            self.assertEqual(invalid["state"], "invalid_configuration")
            path.write_text(json.dumps({"enabled": True, "nodes": [
                dict(item, ssh_host_alias="gway-001")]}))
            invalid, _ = doctor._private_config(
                "gway-002", path=path, pinned_factory=validate,
                required_owner=os.geteuid())
            self.assertEqual(invalid["state"], "binding_mismatch")

    def test_multinode_pin_failure_prevents_false_readiness(self):
        # load_service rejects *all* transport pins if even one node is bad.
        # The local doctor must not declare the target pin valid in that case.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "execute.json"
            def entry(node):
                return {"node": node, "address": ADDRESS,
                        "ssh_host_alias": node,
                        "known_hosts": str(Path(temp) / ("hosts-" + node)),
                        "identity_file": str(Path(temp) / ("id-" + node)),
                        "host_key_sha256": PIN_SHA, "remote_user": "gway-relay"}
            first, second = entry("gway-002"), entry("gway-004")
            path.write_text(json.dumps({"enabled": True, "nodes": [first, second]}))
            path.chmod(0o600)
            validated = []
            def check_pin(**kw):
                validated.append(kw["node"])
                if kw["node"] == "gway-004":
                    raise PermissionError("do-not-expose-private-material")
            state, binding = doctor._private_config(
                "gway-002", path=path, pinned_factory=check_pin,
                required_owner=os.geteuid())
            self.assertEqual(validated, ["gway-002", "gway-004"])
            self.assertEqual(state["state"], "unknown")
            self.assertIsNone(binding)
            self.assertNotIn("do-not-expose", json.dumps(state))

            second["ssh_host_alias"] = "gway-001"
            path.write_text(json.dumps({"enabled": True, "nodes": [first, second]}))
            state, binding = doctor._private_config(
                "gway-002", path=path, pinned_factory=Mock(),
                required_owner=os.geteuid())
            self.assertEqual(state["state"], "invalid_configuration")
            self.assertIsNone(binding)

    def test_other_configured_node_must_also_be_enrolled_and_eligible(self):
        # load_service fails to start if *any* multi-node pin is not bound to
        # current enrolled/attested/reachable identity, even when the target
        # gway-002 itself is fully eligible.
        configured = (
            {"node": "gway-002", "address": ADDRESS},
            {"node": "gway-004", "address": "10.0.1.4"},
        )
        def multi_pin(node):
            return ({"state": "pin_validated_offline"}, {
                "address": ADDRESS, "host_key_sha256": PIN_SHA,
                "configured_nodes": configured,
            })
        def check(rows):
            return doctor.diagnose_node(
                "gway-002", inventory_loader=lambda: {"nodes": rows},
                pin_inspector=multi_pin, ledger_inspector=read_ledger)
        primary = inventory()["nodes"][0]
        absent = check([primary])
        self.assertFalse(absent["ready_for_operator_test"])
        self.assertEqual(absent["pinned_ssh"]["state"], "inventory_binding_mismatch")
        self.assertEqual(absent["terminal_result"]["state"], "unknown")
        other = dict(primary, node="gway-004", address="10.0.1.4")
        for key, value in (("identity_verified", False),
                           ("execute_eligible", False),
                           ("reachable", "unknown"),
                           ("address", "10.0.1.99")):
            with self.subTest(key=key):
                report = check([primary, dict(other, **{key: value})])
                self.assertFalse(report["ready_for_operator_test"])
                self.assertEqual(report["operational"]["state"], "unverified")
        healthy = check([primary, other])
        self.assertTrue(healthy["ready_for_operator_test"])
        self.assertEqual(healthy["operational"]["state"], "unverified")
        self.assertNotIn("10.0.1.4", json.dumps(healthy))

    def test_unsafe_private_execution_ledger_cannot_claim_test_ready(self):
        def unsafe_ledger(node, sha):
            return ({"state": "untrusted"},
                    {"state": "unknown", "evidence": "no_current_result"})
        report = inspect(ledger=unsafe_ledger)
        self.assertFalse(report["ready_for_operator_test"])
        self.assertEqual(report["request_ledger"]["state"], "untrusted")
        self.assertEqual(report["operational"]["state"], "unverified")

    def test_ledger_is_immutable_and_binds_success_to_host_key(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            ledger = folder / "requests.sqlite3"
            with sqlite3.connect(ledger) as db:
                db.execute("CREATE TABLE requests (node TEXT, host_key_sha256 TEXT, "
                           "state TEXT, command TEXT, updated_at TEXT)")
                rows = [
                    ("gway-002", "b" * 64, "succeeded", "id", "2026-11-10T18:00:00+00:00"),
                    ("gway-002", PIN_SHA, "uncertain", "id", "2026-11-10T18:00:00+00:00"),
                    ("gway-002", PIN_SHA, "succeeded", "deployment:[\"app\",\"a\"]",
                     "2026-11-10T18:00:00+00:00"),
                    ("gway-002", PIN_SHA, "succeeded", "id",
                     "2026-11-10T18:00:00+00:00"),
                ]
                db.executemany("INSERT INTO requests VALUES (?,?,?,?,?)", rows)
            ledger.chmod(0o600)
            before = {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
                      for p in folder.iterdir()}
            state, proof = doctor._ledger_evidence("gway-002", PIN_SHA, path=ledger)
            self.assertEqual(state["state"], "readable_checkpoint_only")
            self.assertEqual(proof["state"], "historical_succeeded")
            after = {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
                     for p in folder.iterdir()}
            self.assertEqual(before, after)
            state, proof = doctor._ledger_evidence("gway-004", PIN_SHA, path=ledger)
            self.assertEqual(proof["state"], "unknown")
            ledger.chmod(0o666)
            state, proof = doctor._ledger_evidence("gway-002", PIN_SHA, path=ledger)
            self.assertEqual(state["state"], "untrusted")

    def test_cli_never_returns_operational_success_on_unready_node(self):
        from gway_remote.cli import operations
        parser = build_parser(("system-health",), TARGETS)
        args = parser.parse_args(["node", "doctor", "gway-002", "--json"])
        output = StringIO()
        with patch("gway_remote.node_onboarding_doctor.diagnose_node",
                   return_value=inspect(inventory(eligible=False))), \
             redirect_stdout(output), self.assertRaises(SystemExit) as result:
            operations.dispatch(args, parser)
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue())["eligibility"]["state"], "not_granted")
        with patch("gway_remote.node_onboarding_doctor.diagnose_node",
                   return_value=inspect()), redirect_stdout(StringIO()):
            self.assertTrue(operations.dispatch(args, parser))


if __name__ == "__main__":
    unittest.main()
