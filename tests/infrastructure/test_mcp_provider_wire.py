import unittest
from unittest.mock import patch

from gway_remote.node_exec_protocol import serve_one
from gway_remote.mcp_gateway_federation import FederatedProviders


class ProviderWireTests(unittest.TestCase):
    def test_node_receiver_lists_local_sources(self):
        request = b'{"operation":"provider_list","node":"gway-001","request_id":"0123456789abcdef0123456789abcdef"}'
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.node_exec_protocol.socket.gethostname", return_value="gway-001"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers", return_value=[]), \
             patch("gway_remote.mcp_source_policy.policy_digest", return_value="a"*64), \
             patch("gway_remote.mcp_source_policy.load_source_policy", return_value=((), {})), \
             patch.dict("os.environ", {"GWAY_MCP_SOURCE_POLICY": "/etc/gway-mcp-gateway/sources.json"}):
            response = serve_one(request)
        self.assertEqual(response["result"], {"node": "gway-001", "providers": []})

    def test_watchtower_uses_node_transport(self):
        from tests.helpers.mcp_provider import InvocationSpy
        transport = InvocationSpy(response={"node": "gway-001", "providers": []})
        tools, routes = FederatedProviders(
            transport=transport, nodes=lambda: ("gway-001",)).discover()
        self.assertEqual(tools, [])
        self.assertEqual(routes, {})
        self.assertEqual(transport.calls[0][1], {"operation": "provider_list"})


    def _provider_dispatch(self, request):
        """Exercise real node catalog/dispatch with no SSH, provider or node."""
        import json
        from gway_remote.mcp_source_registry import SourceRegistration

        registration = SourceRegistration(
            source_id="odoo", revision="a" * 40,
            executable="/usr/local/bin/odoo-mcp",
            argv=("/usr/local/bin/odoo-mcp",),
            run_as="arthe", enabled=True)
        read = {"name": "customer_search", "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": True}}
        write = {"name": "customer_update", "inputSchema": {"type": "object"},
                 "annotations": {"readOnlyHint": False}}
        invoked = []

        def stub_provider(*args, **kwargs):
            invoked.append((args, kwargs))
            return {"content": []}

        with (
            patch("gway_remote.node_exec_protocol.require_account"),
            patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                  return_value=[registration]),
            patch("gway_remote.mcp_node_providers._node_registration",
                  side_effect=lambda value: value),
            patch("gway_remote.mcp_node_providers.list_source_tools",
                  return_value=[read, write]),
            patch("gway_remote.mcp_node_providers.call_source_tool",
                  side_effect=stub_provider),
        ):
            reply = serve_one(json.dumps(request).encode(), hostname="gway-001")
        return reply, invoked

    def _provider_request(self, tool="customer_update", **extras):
        return {"operation": "provider_call", "node": "gway-001",
                "request_id": "e" * 32, "provider": "odoo",
                "tool": tool, "arguments": {"id": 1}, **extras}

    def test_unscoped_provider_call_accepts_registered_write(self):
        reply, calls = self._provider_dispatch(self._provider_request())
        self.assertEqual((reply["node"], reply["request_id"]),
                         ("gway-001", "e" * 32))
        self.assertEqual(reply["result"], {"content": []})
        self.assertEqual(len(calls), 1)
        # Stage A adapter only: this does NOT prove a separate OAuth check.
        self.assertEqual(calls[0][1]["authorized_scope"], "execute")

    def test_legacy_provider_call_preserves_read_and_execute(self):
        from gway_remote.mcp_node_providers import NodeProviderError

        with self.assertRaises(NodeProviderError) as denial:
            self._provider_dispatch(
                self._provider_request(authorized_scope="read"))
        self.assertEqual(denial.exception.code, "permission_denied")

        reply, calls = self._provider_dispatch(
            self._provider_request(authorized_scope="execute"))
        self.assertEqual(reply["result"], {"content": []})
        self.assertEqual(len(calls), 1)

        reply, calls = self._provider_dispatch(
            self._provider_request("customer_search",
                                   authorized_scope="read"))
        self.assertEqual(reply["result"], {"content": []})
        self.assertEqual(calls[0][1]["authorized_scope"], "read")

    def test_unscoped_form_does_not_bypass_provider_catalog(self):
        from gway_remote.mcp_node_providers import NodeProviderError

        for malformed in (
            self._provider_request(tool="missing_tool"),
            {**self._provider_request(), "provider": "unregistered"},
        ):
            with self.subTest(malformed=malformed), self.assertRaises(
                    NodeProviderError):
                self._provider_dispatch(malformed)

    def test_both_wire_forms_reject_extra_missing_or_invalid_fields(self):
        import json
        base = self._provider_request()
        invalid = (
            {**base, "authorized_scope": "execute", "unexpected": True},
            {**base, "untrusted_principal": "f" * 24},
            {key: value for key, value in base.items() if key != "arguments"},
            {**base, "authorized_scope": "bogus"},
            {**base, "authorized_scope": None},
            {**base, "node": "gway-002"},
            {**base, "request_id": "not-a-request-id"},
            {**base, "operation": "provider_list"},
        )
        with (
            patch("gway_remote.node_exec_protocol.require_account"),
            patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                  return_value=[]) as discovery,
        ):
            for request in invalid:
                with self.subTest(request=request), self.assertRaises(
                        (ValueError, PermissionError)):
                    serve_one(json.dumps(request).encode(),
                              hostname="gway-001")
        # Invalid wire shape is rejected before any provider invocation;
        # invalid legacy scope may reach discovery but never dispatch.
        self.assertLessEqual(discovery.call_count, 2)

    def test_unrelated_operations_do_not_acquire_an_unscoped_variant(self):
        import json

        request = {"operation": "provider_list", "node": "gway-001",
                   "request_id": "e" * 32, "arguments": {}}
        with patch("gway_remote.node_exec_protocol.require_account"):
            with self.assertRaises(ValueError):
                serve_one(json.dumps(request).encode(), hostname="gway-001")


    def test_sender_uses_unscoped_execute_and_legacy_read_wire(self):
        from gway_remote.mcp_provider_transport import ProviderTransport
        from unittest.mock import Mock
        from types import SimpleNamespace

        captured = []
        def send(payload):
            captured.append(payload)
            return {"node": "gway-001", "request_id": payload["request_id"],
                    "result": {"content": []}}

        with patch("gway_remote.mcp_provider_transport.pinned_transport",
                   return_value=SimpleNamespace(invoke=send)):
            client = ProviderTransport(object())
            for scope in ("execute", "read"):
                result = client.invoke(
                    "gway-001", {"operation": "provider_call",
                                 "provider": "odoo", "tool": "customer_search",
                                 "arguments": {}},
                    trusted_scope=scope)
                self.assertEqual(result, {"content": []})
        self.assertEqual(len(captured), 2)
        self.assertEqual(set(captured[0]),
                         {"operation", "node", "request_id",
                          "provider", "tool", "arguments"})
        self.assertEqual(captured[1]["authorized_scope"], "read")
        self.assertEqual(set(captured[1]), set(captured[0]) | {"authorized_scope"})

    def test_ssh_transport_accepts_both_exact_provider_call_shapes(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock
        from gway_remote.watchtower_exec_transport import SSHTransport

        node = SimpleNamespace(
            node="gway-001", known_hosts="/tmp/test-known-hosts",
            ssh_host_alias="gway-001", identity_file="/tmp/test-key",
            remote_user="gway-relay", wireguard_address="10.90.0.2")
        replies = []
        def fake_ssh(argv, *, input, **kwargs):
            message = json.loads(input)
            replies.append(message)
            return SimpleNamespace(stdout=json.dumps(
                {"node": "gway-001", "request_id": message["request_id"],
                 "result": {"content": []}}).encode())
        fake = Mock(side_effect=fake_ssh)
        transport = SSHTransport(node, run=fake)
        original = self._provider_request(tool="customer_search")
        for request in (original, {**original, "authorized_scope": "read"}):
            self.assertEqual(transport.invoke(request)["node"], "gway-001")
        self.assertEqual(len(replies), 2)
        self.assertNotIn("authorized_scope", replies[0])
        self.assertEqual(replies[1]["authorized_scope"], "read")
        before = fake.call_count
        for bad in ({**original, "unknown": True},
                    {key: val for key, val in original.items()
                     if key != "arguments"},
                    {**original, "authorized_scope": "read", "extra": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                transport.invoke(bad)
        self.assertEqual(fake.call_count, before)


    def test_gateway_reuses_exact_discovered_routes_without_second_list(self):
        from tests.helpers.mcp_provider import InvocationSpy, provider_reply
        from tests.helpers.mcp_federation import fixture_tool

        spy = InvocationSpy(response=provider_reply(
            tools=[fixture_tool("lookup", read=True),
                   fixture_tool("update")]))
        gateway = FederatedProviders(
            transport=spy, nodes=lambda: ("gway-001",))
        _, routes = gateway.discover()
        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0][1]["operation"], "provider_list")

        # The same request routes are used after the public OAuth admission.
        spy.response = {"content": []}
        self.assertEqual(
            gateway.call("odoo__lookup", {"id": 1},
                         authorized_scope="read", routes=routes),
            {"content": []})
        self.assertEqual([x[1]["operation"] for x in spy.calls],
                         ["provider_list", "provider_call"])
        self.assertEqual(spy.calls[1][2], "read")

        # A stale snapshot is not permission to upgrade read to execute.
        with self.assertRaises(PermissionError):
            gateway.call("odoo__update", {"id": 1},
                         authorized_scope="read", routes=routes)
        self.assertEqual(len(spy.calls), 2)

        with self.assertRaises(ValueError):
            gateway.call("odoo__missing", {},
                         authorized_scope="execute", routes=routes)
        self.assertEqual(len(spy.calls), 2)


if __name__ == "__main__":
    unittest.main()
