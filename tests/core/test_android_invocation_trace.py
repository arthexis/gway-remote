"""Hermetic correlation of gateway, node, Android runner and input boundary."""
import hashlib
import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gway_remote import android_invocation_trace as trace
from gway_remote import android_scenario_runner as runner
from gway_remote import mcp_android as android
from gway_remote import mcp_node_providers as providers
from gway_remote import mcp_provider_transport as transport
from gway_remote import mcp_source_stdio as stdio
from gway_remote import node_exec_protocol as protocol
from gway_remote.mcp_source_registry import SourceRegistration

RID = "a" * 32
OTHER = "b" * 32
SCENARIO = "developer-options-from-search-v1"
PKG = "com.android.settings.intelligence"
FIELD = PKG + ":id/search_src_text"


def snapshot(query):
    field = {"package": PKG, "resource_id": FIELD, "text": query,
             "focused": True, "enabled": True}
    extras = ([{"package": PKG, "resource_id": "android:id/title",
                "text": "Permanecer activo"},
               {"package": PKG, "resource_id": PKG + ":id/breadcrumb",
                "text": "Opciones de desarrollador"}] if query == "Permanecer activo" else [])
    return {"truncated": False, "elements": [field, *extras]}


class Device(android.Device):
    def serial(self):
        return "private-device-serial"

    def screen_state(self, serial):
        return {"screen_on": True, "locked": False, "rotation": 0}

    def size(self, serial):
        return 1080, 2220

    def ui_tree(self, serial, *, navigation_details=False):
        return snapshot("Permanecer activo")


class InvocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "receipts"
        self.root.mkdir(mode=0o700)

    def test_end_to_end_request_identity_and_pre_dispatch_failure(self):
        declaration = next(tool for tool in android.TOOLS if tool["name"] == "scenario_run")
        registration = SourceRegistration("android", "c" * 40, "/usr/bin/true",
                                          ("/usr/bin/true",), "arthe", True)
        device = Device(run=Mock(side_effect=AssertionError("no subprocess permitted")))
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        def rpc(rid, method, params):
            return android.handle_rpc({"jsonrpc": "2.0", "id": rid,
                                       "method": method, "params": params})
        session.request.side_effect = rpc
        ssh = Mock()
        ssh.invoke.side_effect = lambda payload: protocol.serve_one(
            json.dumps(payload).encode(), hostname="gway-001")
        with (patch.object(transport, "pinned_transport", return_value=ssh),
              patch.object(transport.secrets, "token_hex", return_value=RID),
              patch.object(protocol, "require_account"),
              patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                    return_value=[registration]),
              patch.object(providers, "_node_registration", return_value=registration),
              patch.object(providers, "_catalog",
                           return_value={"read": [], "execute_required": [declaration]}),
              patch.object(stdio, "_Session", return_value=session),
              patch.object(android, "Device", return_value=device),
              patch.object(runner, "_receipt_root", return_value=self.root)):
            response = transport.ProviderTransport(Mock()).invoke("gway-001", {
                "operation": "provider_call", "provider": "android", "tool": "scenario_run",
                "arguments": {"scenario_id": SCENARIO, "operation_id": OTHER}}, trusted_scope="execute")
        body = json.loads(response["content"][0]["text"])
        self.assertEqual(body["invocation_id"], RID)
        self.assertEqual(body["operation_id"], OTHER)
        self.assertEqual(body["receipt_id"], OTHER)
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["action_invocations"], 0)
        self.assertTrue(body["node_transport"]["matched"])
        self.assertTrue(body["watchtower_transport"]["matched"])
        for stage in ("node_transport", "watchtower_transport"):
            self.assertEqual(body[stage]["invocation_id"], RID)
        self.assertEqual(ssh.invoke.call_count, 1)
        self.assertEqual(ssh.invoke.call_args.args[0]["request_id"], RID)
        session.request.assert_any_call(RID, "tools/call", {
            "name": "scenario_run", "arguments": {"scenario_id": SCENARIO, "operation_id": OTHER}})
        receipt = runner.result(body["receipt_id"], root=self.root)
        self.assertEqual(receipt["sha256"], body["receipt_sha256"])
        evidence = receipt["manifest"]["invocation_trace"]
        self.assertEqual(evidence["invocation_id"], RID)
        self.assertTrue(evidence["complete"])
        self.assertEqual(evidence["origin"], "transport")
        by_stage = {entry["stage"]: entry for entry in evidence["events"]}
        self.assertEqual(by_stage["first_preflight"]["screen"], "settings_search_results")
        self.assertFalse(by_stage["first_preflight"]["empty"])
        self.assertTrue(by_stage["first_preflight"]["focused"])
        self.assertFalse(by_stage["first_preflight"]["target_resolved"])
        self.assertEqual(by_stage["transition_rejected"]["reason"], "source_not_actionable")
        self.assertEqual(by_stage["runner_step_end"]["dispatch"], "not_attempted")
        self.assertNotIn("input_attempt", by_stage)
        self.assertNotIn("private-device-serial", json.dumps(receipt))
        self.assertNotIn("Permanecer activo", json.dumps(receipt))
        device.run.assert_not_called()

    def test_successful_reviewed_recipe_preserves_two_action_budget(self):
        initial = snapshot("Buscar")
        results = snapshot("Permanecer activo")
        results["elements"][1].update({"resource_id": PKG + ":id/result", "enabled": True,
                                        "clickable": True, "bounds": "[100,300][500,450]"})
        done = {"truncated": False, "elements": [
            {"package": "com.android.settings", "text": "Opciones de desarrollador"},
            {"package": "com.android.settings", "text": "Permanecer activo"}]}
        class Sequence(Device):
            def ui_tree(self, serial, *, navigation_details=False):
                return next(self.trees)
        dev = Sequence(run=Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")))
        dev.trees = iter([initial, initial, results, results,
                          results, results, done, done])
        before = runner.preview(SCENARIO)
        with trace.invocation(RID, "scenario_run", self.root) as invocation:
            invocation.acquired()
            result = runner.run(SCENARIO, device=dev, receipt_root=self.root)
        receipt = runner.result(result["receipt_id"], root=self.root)
        self.assertEqual(receipt["manifest"]["spec_sha256"], before["spec_sha256"])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["action_invocations"], 2)
        self.assertEqual(dev.run.call_count, 2)
        evidence = receipt["manifest"]["invocation_trace"]
        self.assertTrue(evidence["complete"])
        self.assertEqual([e["kind"] for e in evidence["events"] if e["stage"] == "input_attempt"],
                         ["text", "tap"])
        self.assertLessEqual((self.root / (result["receipt_id"] + ".json")).stat().st_size, 8192)

    def test_actual_input_attempt_is_independent_and_recent_history_bounded(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""))
        device = android.Device(run=run)
        with trace.invocation(RID, "text", self.root) as prior:
            prior.acquired()
            for _ in range(12):
                device.adb("private-device-serial", "shell", "input", "text", "private-value")
            device.adb("private-device-serial", "shell", "getprop", "private-property")
            self.assertEqual(sum(e["stage"] == "input_attempt" for e in prior.events), 12)
        with trace.invocation(OTHER, "scenario_run", self.root) as current:
            current.acquired()
            evidence = current.evidence()
        self.assertEqual(len(evidence["recent_input_attempts"]), 8)
        self.assertTrue(all(entry["invocation_id"] == RID and entry["kind"] == "text"
                            for entry in evidence["recent_input_attempts"]))
        path = self.root / ".recent-inputs-v1"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        for value in ("private-device-serial", "private-value", "private-property"):
            self.assertNotIn(value, path.read_text())
            self.assertNotIn(value, json.dumps(evidence))
        self.assertEqual(run.call_count, 13)

    def test_uncertain_actual_input_is_marked_without_raw_error(self):
        device = android.Device(run=Mock(side_effect=subprocess.TimeoutExpired(["private"], 1)))
        with trace.invocation(RID, "text", self.root) as invocation:
            invocation.acquired()
            with self.assertRaises(android.AndroidError):
                device.adb("private-device-serial", "shell", "input", "text", "private-value")
            evidence = invocation.evidence()
        self.assertEqual([e["stage"] for e in evidence["events"]][-2:],
                         ["input_attempt", "input_error"])
        self.assertNotIn("private", json.dumps(evidence))

    def test_transport_mismatch_and_scope_preserve_contract(self):
        body = {"invocation_id": OTHER, "receipt_id": RID}
        result = {"content": [{"type": "text", "text": json.dumps(body)}]}
        tagged = trace.annotate_transport(result, RID, "watchtower_transport", 12)
        self.assertFalse(json.loads(tagged["content"][0]["text"])["watchtower_transport"]["matched"])
        self.assertEqual(json.loads(result["content"][0]["text"]), body)
        registration = SourceRegistration("android", "c" * 40, "/usr/bin/true",
                                          ("/usr/bin/true",), "arthe", True)
        declaration = next(t for t in android.TOOLS if t["name"] == "scenario_run")
        with patch.object(stdio, "_Session") as session:
            with self.assertRaises(stdio.SourceProtocolError):
                stdio.call_source_tool(registration, "scenario_run", {"scenario_id": SCENARIO},
                                       declaration, authorized_scope="read", invocation_id=RID)
            with self.assertRaises(stdio.SourceProtocolError):
                stdio.call_source_tool(registration, "scenario_run", {"scenario_id": SCENARIO},
                                       declaration, authorized_scope="execute", invocation_id="invalid")
            session.assert_not_called()
        with patch.object(android, "Device") as device:
            denied = android.call_tool("scenario_run", {"scenario_id": SCENARIO,
                                                         "invocation_id": RID})
            self.assertTrue(denied["isError"])
            device.assert_not_called()

    def test_unsafe_history_is_not_followed_and_trace_reports_incomplete(self):
        private = Path(self.temp.name) / "private"
        private.write_text("private")
        (self.root / ".recent-inputs-v1").symlink_to(private)
        with trace.invocation(RID, "scenario_run", self.root) as invocation:
            invocation.acquired()
            invocation.input_attempt("text")
            evidence = invocation.evidence()
        self.assertFalse(evidence["complete"])
        self.assertEqual(evidence["recent_input_attempts"], [])
        self.assertEqual(private.read_text(), "private")
        self.assertEqual([e["stage"] for e in evidence["events"]][-1], "input_attempt")


if __name__ == "__main__":
    unittest.main()
