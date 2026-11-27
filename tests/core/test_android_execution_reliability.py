"""Reliability regressions: actual input boundary, durable identity, and nested budgets."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gway_remote import android_execution_contract as execution
from gway_remote import android_operation_journal as journal
from gway_remote import android_scenario_runner as runner
from gway_remote import mcp_android as android
from gway_remote import mcp_node_providers as providers
from gway_remote import mcp_provider_transport as transport
from gway_remote import mcp_source_stdio as stdio
from gway_remote import watchtower_exec_transport as ssh_transport
from gway_remote.mcp_source_registry import SourceRegistration

OP = "a" * 32
OTHER = "b" * 32
RID = "c" * 32
SCENARIO = "developer-options-from-search-v1"


def body(response):
    return json.loads(response["content"][0]["text"])


class Device(android.Device):
    def __init__(self, *, abort=False):
        super().__init__(run=Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")))
        self.abort = abort
        self.screen = "settings_search_results"

    def semantic_transition(self, source, destination):
        self.adb("private-serial", "shell", "input",
                 "text" if source == "settings_search" else "tap", "private-value")
        return {"status": "confirmed", "dispatched": True}

    def invoke(self, name, arguments):
        if name == "navigation_model":
            return {"status": "recognized", "screen": self.screen}
        if name == "scenario_run" and self.abort:
            # Simulate termination after durable input intent, before receipt.
            self.adb("private-serial", "shell", "input", "text", "private-value")
            raise OSError("private error")
        return super().invoke(name, arguments)


class ExecutionReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "receipts"
        self.root.mkdir(mode=0o700)
        patcher = patch.object(runner, "_receipt_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, device, name, args):
        with patch.object(android, "Device", return_value=device):
            return body(android.call_tool(name, args, invocation_id=RID))

    def test_missing_identity_fails_closed_before_device(self):
        with patch.object(android, "Device") as dev:
            self.assertEqual(body(android.call_tool("scenario_run", {"scenario_id": SCENARIO}))["error"],
                             "operation_id_required")
            dev.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_completed_identity_never_replays_and_receipt_is_stable(self):
        dev = Device()
        args = {"scenario_id": SCENARIO, "operation_id": OP}
        result = self.call(dev, "scenario_run", args)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["receipt_id"], OP)
        self.assertEqual(result["input_attempts"], 2)
        self.assertEqual(dev.run.call_count, 2)
        receipt = runner.result(OP, root=self.root)
        self.assertEqual(receipt["sha256"], result["receipt_sha256"])
        self.assertEqual(receipt["manifest"]["operation_id"], OP)
        self.assertEqual(receipt["manifest"]["spec_sha256"], runner.preview(SCENARIO)["spec_sha256"])
        replay = self.call(dev, "scenario_run", args)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt_sha256"], receipt["sha256"])
        self.assertEqual(dev.run.call_count, 2)
        conflict = self.call(dev, "scenario_run", {"scenario_id": "home-screen-stability-v1",
                                                    "operation_id": OP})
        self.assertEqual(conflict["error"], "operation_binding_conflict")
        self.assertEqual(dev.run.call_count, 2)

    def test_interrupted_claim_blocks_same_and_new_id_until_observed_reconciliation(self):
        dev = Device(abort=True)
        args = {"scenario_id": SCENARIO, "operation_id": OP}
        result = self.call(dev, "scenario_run", args)
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["retryable"])
        self.assertTrue(result["reconciliation_required"])
        self.assertEqual(dev.run.call_count, 1)
        self.assertFalse((self.root / (OP + ".json")).exists())
        state = self.call(dev, "scenario_status", {"operation_id": OP})
        self.assertEqual(state["input_attempts"], 1)
        self.assertEqual(state["invocation_id"], RID)
        self.assertTrue(self.call(dev, "scenario_run", args)["replayed"])
        blocked = self.call(dev, "scenario_run", {"scenario_id": SCENARIO, "operation_id": OTHER})
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["blocking_operation_id"], OP)
        self.assertEqual(dev.run.call_count, 1)
        mismatch = self.call(dev, "scenario_reconcile", {"operation_id": OP,
                                                        "expected_screen": "developer_options"})
        self.assertTrue(mismatch["reconciliation_required"])
        reconciled = self.call(dev, "scenario_reconcile", {"operation_id": OP,
                                                            "expected_screen": "settings_search_results"})
        self.assertTrue(reconciled["reconciled"])
        self.assertFalse(reconciled["reconciliation_required"])
        self.assertEqual(reconciled["status"], "uncertain")
        self.assertTrue(self.call(dev, "scenario_run", args)["replayed"])
        self.assertEqual(dev.run.call_count, 1)
        dev.abort = False
        self.assertEqual(self.call(dev, "scenario_run", {"scenario_id": SCENARIO,
                                                         "operation_id": OTHER})["status"], "passed")
        self.assertEqual(dev.run.call_count, 3)

    def test_receipt_recoverable_if_process_dies_before_terminal_journal_update(self):
        dev = Device()
        with patch.object(journal.Claim, "finish", side_effect=OSError("interrupted")):
            uncertain = self.call(dev, "scenario_run", {"scenario_id": SCENARIO, "operation_id": OP})
        self.assertEqual(uncertain["status"], "uncertain")
        recovered = self.call(dev, "scenario_status", {"operation_id": OP})
        self.assertEqual(recovered["status"], "passed")
        self.assertEqual(recovered["receipt_id"], OP)
        self.assertEqual(dev.run.call_count, 2)
        self.assertTrue(self.call(dev, "scenario_run", {"scenario_id": SCENARIO,
                                                        "operation_id": OP})["replayed"])
        self.assertEqual(dev.run.call_count, 2)

    def test_input_intent_write_failure_prevents_subprocess(self):
        dev = Device()
        claim, _ = journal.begin(self.root, OP, SCENARIO, runner.preview(SCENARIO)["spec_sha256"], 2)
        with execution.budget(claim=claim), patch.object(journal, "_write", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                dev.adb("private-serial", "shell", "input", "text", "private-value")
        dev.run.assert_not_called()
        self.assertTrue(journal.status(self.root, OP)["reconciliation_required"])

    def test_deadline_caps_subprocess_and_prevents_late_input(self):
        now = [0]
        dev = Device()
        with execution.budget(seconds=10, clock=lambda: now[0]):
            now[0] = 9
            dev.adb("private-serial", "shell", "getprop", "private")
            self.assertEqual(dev.run.call_args.kwargs["timeout"], 1)
            now[0] = 10
            with self.assertRaises(execution.DeadlineExceeded):
                dev.adb("private-serial", "shell", "input", "text", "private")
        self.assertEqual(dev.run.call_count, 1)
        self.assertLess(execution.RUN_SECONDS, execution.STDIO_SECONDS)
        self.assertLess(execution.STDIO_SECONDS, execution.SSH_SECONDS)

    def test_provider_timeout_is_typed_uncertain_without_replay(self):
        declaration = next(t for t in android.TOOLS if t["name"] == "scenario_run")
        reg = SourceRegistration("android", "a"*40, "/usr/bin/true", ("/usr/bin/true",), "arthe", True)
        args = {"scenario_id": SCENARIO, "operation_id": OP}
        with (patch.object(providers, "_node_registration", return_value=reg),
              patch.object(providers, "_catalog", return_value={"read": [], "execute_required": [declaration]}),
              patch.object(providers, "call_source_tool", side_effect=stdio.SourceProtocolError("provider_timeout")) as source):
            response = providers.provider_call([reg], provider="android", tool="scenario_run",
                                               arguments=args, authorized_scope="execute", invocation_id=RID)
            self.assertEqual(body(response)["error"], "provider_timeout")
            self.assertEqual(body(response)["operation_id"], OP)
            self.assertFalse(body(response)["retryable"])
            self.assertEqual(source.call_args.kwargs["timeout"], execution.STDIO_SECONDS)
            with self.assertRaises(providers.NodeProviderError):
                providers.provider_call([reg], provider="android", tool="scenario_run",
                                        arguments=args, authorized_scope="read", invocation_id=RID)
            self.assertEqual(source.call_count, 1)

    def test_ssh_timeout_is_typed_uncertain_for_only_scenario(self):
        req = {"operation": "provider_call", "provider": "android", "tool": "scenario_run",
               "arguments": {"scenario_id": SCENARIO, "operation_id": OP}}
        connection = Mock()
        connection.invoke.side_effect = subprocess.TimeoutExpired(["private"], 65)
        with patch.object(transport, "pinned_transport", return_value=connection):
            out = body(transport.ProviderTransport(Mock()).invoke("gway-001", req, trusted_scope="execute"))
            self.assertEqual(out["error"], "transport_timeout")
            self.assertEqual(out["operation_id"], OP)
            self.assertFalse(out["retryable"])
            self.assertEqual(connection.invoke.call_count, 1)
            with self.assertRaises(PermissionError):
                transport.ProviderTransport(Mock()).invoke("gway-001", req, trusted_scope="read")
            self.assertEqual(connection.invoke.call_count, 1)
        self.assertNotIn("private", json.dumps(out))

    def test_corrupt_terminal_receipt_does_not_admit_new_operation(self):
        dev = Device()
        result = self.call(dev, "scenario_run", {"scenario_id": SCENARIO, "operation_id": OP})
        self.assertEqual(result["status"], "passed")
        path = self.root / (OP + ".json")
        manifest = json.loads(path.read_text())
        manifest["duration_ms"] += 1
        path.write_text(json.dumps(manifest))
        self.assertEqual(self.call(dev, "scenario_status", {"operation_id": OP})["status"], "uncertain")
        self.assertEqual(self.call(dev, "scenario_run", {"scenario_id": SCENARIO,
                                                         "operation_id": OTHER})["status"], "blocked")
        self.assertEqual(dev.run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
