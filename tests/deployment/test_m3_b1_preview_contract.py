"""M3 B1: non-executing preview and durable-job protocol validation."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from gway_remote import mcp_bearer_gateway as gateway
from gway_remote import node_exec_contract as jobs


VERIFIED = {"nodes": [
    {"node": "gway-001", "registered": True, "identity_verified": True,
     "execute_available": False, "reachable": "reachable"},
    {"node": "gway-002", "registered": True, "identity_verified": False,
     "execute_available": False, "reachable": "reachable"},
]}


class ContractTests(unittest.TestCase):
    def test_preview_literal_shell_string_and_no_dispatch(self):
        command = "df -h && uptime; printf '%s' '$HOME' | cat"
        data = jobs.preview("gway-001", command, VERIFIED)
        self.assertEqual(data["command"], command)
        self.assertEqual(data["status"], "preview_only")
        self.assertFalse(data["execute_available"])
        self.assertFalse(data["authorization"]["approval_required"])
        self.assertEqual(data["authorization"]["required_scope"], "gway:execute")
        self.assertEqual(data["limits"]["wait_seconds"], 10)
        self.assertEqual(len(data["command_sha256"]), 64)
        self.assertNotIn("address", data)

    def test_preview_matches_capabilities_when_execution_enabled(self):
        enabled = {"nodes": [
            {"node": "gway-001", "registered": True, "identity_verified": True,
             "execute_available": True, "reachable": "reachable"},
        ]}
        result = jobs.preview("gway-001", "hostname", enabled)
        self.assertTrue(result["execute_available"])
        self.assertEqual(result["status"], "preview_only")
        self.assertFalse(result["authorization"]["approval_required"])

        disabled = {"nodes": [{**enabled["nodes"][0], "execute_available": False}]}
        self.assertFalse(jobs.preview("gway-001", "hostname", disabled)["execute_available"])

    def test_invalid_target_or_shell_rejected(self):
        for node in ("../../tmp", "watchtower", "gway-002", "gway-999"):
            with self.subTest(node=node), self.assertRaises(ValueError):
                jobs.preview(node, "uptime", VERIFIED)
        for command in ("", "   ", "hello\x00world", "a" * 4097, 42, None):
            with self.subTest(command=repr(command)), self.assertRaises(ValueError):
                jobs.preview("gway-001", command, VERIFIED)
        self.assertNotEqual(jobs.command_digest("gway-001", "uptime", "identity"),
                            jobs.command_digest("gway-001", "uptime; true", "identity"))

    def test_rejects_incomplete_or_unavailable_identity(self):
        for inventory in ({}, {"nodes": []}, {"nodes": [{"node": "gway-001",
               "registered": True, "identity_verified": False, "execute_available": True}]}):
            with self.assertRaises(ValueError):
                jobs.preview("gway-001", "uptime", inventory)

    def test_job_state_transitions_fail_closed(self):
        for first, second in (("queued", "running"), ("queued", "cancelled"),
                              ("running", "succeeded"), ("running", "unknown")):
            self.assertEqual(jobs.validate_transition(first, second), second)
        for first, second in (("queued", "succeeded"), ("failed", "running"),
                              ("running", "running"), ("ghost", "running")):
            with self.assertRaises(ValueError):
                jobs.validate_transition(first, second)

    def test_result_chunk_bound_and_schema(self):
        valid = {"schema": 1, "request_id": "a" * 32, "node": "gway-001",
                 "status": "running", "stdout": "working", "stderr": "",
                 "truncated": False, "cursor": None, "exit_code": None,
                 "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None}
        self.assertEqual(jobs.validate_result(valid), valid)
        for diff in ({"stdout": "x" * 16385}, {"status": "imaginary"},
                     {"exit_code": 0}, {"cursor": 8}, {"truncated": "false"},
                     {"request_id": "../invalid"}, {"schema": 2}):
            with self.subTest(diff=diff), self.assertRaises(ValueError):
                jobs.validate_result({**valid, **diff})


class GatewayTests(unittest.TestCase):
    def test_preview_is_allowlisted_but_never_executes(self):
        names = [tool["name"] for tool in gateway.NODE_TOOLS]
        self.assertIn("node_exec_preview", names)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(gateway.inspect_rpc(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "node_exec_preview",
                       "arguments": {"node": "gway-001", "command": "uptime"}}
        }).encode()))
        # Execution names are now recognized by the parser, but Handler
        # requires both gway:execute scope and an opt-in execution service.
        for gated in ("node_exec", "node_cancel", "node_result"):
            raw = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": gated, "arguments": {}}
            }).encode()
            self.assertTrue(gateway.inspect_rpc(raw))
            self.assertTrue(gateway.payload_is_exec(raw))
        with patch.object(gateway, "local_node_result", wraps=gateway.local_node_result):
            with patch("gway_remote.node_registry_inventory.public_nodes", return_value=VERIFIED):
                record = gateway.local_node_result("node_exec_preview",
                     {"node": "gway-001", "command": "sleep 20"})
                self.assertEqual(record["status"], "preview_only")
                with self.assertRaises(ValueError):
                    gateway.local_node_result("node_exec", {"node": "gway-001", "command": "uptime"})


if __name__ == "__main__":
    unittest.main()
