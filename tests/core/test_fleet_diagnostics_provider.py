"""Offline MCP diagnostics provider contract and permission tests."""
import unittest
from unittest.mock import patch

from gway_remote.fleet_diagnostics_provider import dispatch, TOOLS


class FleetDiagnosticsProviderTests(unittest.TestCase):
    def test_catalog_is_strictly_read_only(self):
        response = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertEqual([t["name"] for t in response["result"]["tools"]], ["hardware", "status"])
        for tool in TOOLS:
            self.assertIs(tool["annotations"]["readOnlyHint"], True)
            self.assertIs(tool["inputSchema"]["additionalProperties"], False)

    def test_calls_existing_probes_only(self):
        for name, module, function, schema in (
            ("hardware", "gway_remote.fleet_diagnostics_provider.inspect", None, "gway-remote/hardware/v1"),
            ("status", "gway_remote.fleet_diagnostics_provider.status", None, "gway-remote/status/v1")):
            with self.subTest(name=name), patch(module, return_value={"schema": schema}) as probe:
                reply = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": name, "arguments": {}}})
                self.assertIn(schema, reply["result"]["content"][0]["text"])
                if name == "status":
                    probe.assert_called_once_with(depth="quick")
                else:
                    probe.assert_called_once_with()

    def test_stdio_initialize_discover_and_call_contract(self):
        import json
        from gway_remote.mcp_tool_scope import required_scope
        initialized = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-03-26",
                                           "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-03-26")
        self.assertIsNone(dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        listed = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual([required_scope(tool) for tool in listed["result"]["tools"]], ["read", "read"])
        with patch("gway_remote.fleet_diagnostics_provider.inspect", return_value={
            "schema": "gway-remote/hardware/v1", "checked_at": "2026-11-09T00:00:00+00:00",
            "host": {"cpu_temperature_c": 42}}):
            reply = dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": "hardware", "arguments": {}}})
        self.assertEqual(reply["id"], 3)
        self.assertEqual(json.loads(reply["result"]["content"][0]["text"])["host"]["cpu_temperature_c"], 42)

    def test_unknown_tool_and_arguments_rejected_without_probes(self):
        with patch("gway_remote.fleet_diagnostics_provider.inspect") as hw, \
             patch("gway_remote.fleet_diagnostics_provider.status") as status:
            for name, args in (("exec", {}), ("hardware", {"command": "id"}),
                               ("status", {"depth": "deep"})):
                with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                    dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": name, "arguments": args}})
            hw.assert_not_called()
            status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
