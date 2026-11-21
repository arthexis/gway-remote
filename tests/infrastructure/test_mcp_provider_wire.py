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

    def test_legacy_provider_call_is_rejected_before_discovery(self):
        import json
        for scope in ("read", "execute", None, "bogus"):
            with patch("gway_remote.node_exec_protocol.require_account"), (
                patch("gway_remote.mcp_installed_providers.discover_installed_providers")
            ) as discovery:
                with self.subTest(scope=scope), self.assertRaises(ValueError):
                    serve_one(json.dumps(self._provider_request(
                        authorized_scope=scope)).encode(), hostname="gway-001")
                discovery.assert_not_called()

    def test_unscoped_form_does_not_bypass_provider_catalog(self):
        from gway_remote.mcp_node_providers import NodeProviderError

        for malformed in (
            self._provider_request(tool="missing_tool"),
            {**self._provider_request(), "provider": "unregistered"},
        ):
            with self.subTest(malformed=malformed), self.assertRaises(
                    NodeProviderError):
                self._provider_dispatch(malformed)

    def test_exact_wire_rejects_extra_missing_and_wrong_node(self):
        import json
        base = self._provider_request()
        invalid = (
            {**base, "authorized_scope": "read"},
            {**base, "authorized_scope": "execute"},
            {**base, "untrusted_principal": "f" * 24},
            {key: value for key, value in base.items() if key != "arguments"},
            {**base, "node": "gway-002"},
            {**base, "request_id": "not-a-request-id"},
            {**base, "operation": "provider_list"},
        )
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                   return_value=[]) as discovery:
            for request in invalid:
                with self.subTest(request=request), self.assertRaises(
                        (ValueError, PermissionError)):
                    serve_one(json.dumps(request).encode(), hostname="gway-001")
        discovery.assert_not_called()

    def test_unrelated_operations_do_not_acquire_an_unscoped_variant(self):
        import json

        request = {"operation": "provider_list", "node": "gway-001",
                   "request_id": "e" * 32, "arguments": {}}
        with patch("gway_remote.node_exec_protocol.require_account"):
            with self.assertRaises(ValueError):
                serve_one(json.dumps(request).encode(), hostname="gway-001")


    def test_sender_emits_only_scope_free_operation_bound_wire(self):
        from gway_remote.mcp_provider_transport import ProviderTransport
        from types import SimpleNamespace

        captured = []
        def send(payload):
            captured.append(payload)
            return {"node": "gway-001", "request_id": payload["request_id"],
                    "result": {"content": []}}

        with patch("gway_remote.mcp_provider_transport.pinned_transport",
                   return_value=SimpleNamespace(invoke=send)):
            client = ProviderTransport(object())
            for operation, scope in (("provider_call", "execute"),
                                     ("provider_read", "read")):
                result = client.invoke(
                    "gway-001", {"operation": operation,
                                 "provider": "odoo", "tool": "customer_search",
                                 "arguments": {}}, trusted_scope=scope)
                self.assertEqual(result, {"content": []})
            for operation, scope in (("provider_call", "read"),
                                     ("provider_read", "execute")):
                with self.assertRaises(PermissionError):
                    client.invoke(
                        "gway-001", {"operation": operation, "provider": "odoo",
                                     "tool": "customer_search", "arguments": {}},
                        trusted_scope=scope)
        self.assertEqual(len(captured), 2)
        for payload, operation in zip(captured, ("provider_call", "provider_read")):
            self.assertEqual(payload["operation"], operation)
            self.assertEqual(set(payload),
                             {"operation", "node", "request_id", "provider",
                              "tool", "arguments"})

    def test_ssh_transport_rejects_legacy_scope_before_ssh(self):
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
        self.assertEqual(transport.invoke(original)["node"], "gway-001")
        self.assertEqual(len(replies), 1)
        self.assertNotIn("authorized_scope", replies[0])
        before = fake.call_count
        for bad in ({**original, "authorized_scope": "read"},
                    {**original, "authorized_scope": "execute"},
                    {**original, "unknown": True},
                    {key: val for key, val in original.items()
                     if key != "arguments"},
                    {**original, "authorized_scope": "read", "extra": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                transport.invoke(bad)
        self.assertEqual(fake.call_count, before)

    def test_gateway_reuses_exact_discovered_routes_without_second_list(self):
        from tests.helpers.mcp_provider import InvocationSpy, provider_reply
        from tests.helpers.mcp_federation import fixture_tool

        advertised = provider_reply(
            tools=[fixture_tool("lookup", read=True), fixture_tool("update")])
        advertised["providers"][0]["supports_provider_read"] = True
        spy = InvocationSpy(response=advertised)
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
                         ["provider_list", "provider_read"])
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


    def test_provider_read_is_bound_to_live_tool_classification(self):
        from gway_remote.mcp_node_providers import NodeProviderError

        # No caller-provided OAuth scope. A registered read operation is allowed.
        read_request = self._provider_request(tool="customer_search")
        read_request["operation"] = "provider_read"
        reply, calls = self._provider_dispatch(read_request)
        self.assertEqual(reply["result"], {"content": []})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["authorized_scope"], "read")

        # The identical RPC must not invoke a write-classified tool.
        write_request = self._provider_request(tool="customer_update")
        write_request["operation"] = "provider_read"
        with self.assertRaises(NodeProviderError) as failure:
            self._provider_dispatch(write_request)
        self.assertEqual(failure.exception.code, "permission_denied")

    def test_provider_read_is_still_exact_and_node_bound(self):
        import json

        request = self._provider_request(tool="customer_search")
        request["operation"] = "provider_read"
        invalid = (
            {**request, "authorized_scope": "execute"},
            {**request, "authorized_scope": "read"},
            {**request, "caller": "external"},
            {**request, "node": "gway-002"},
            {**request, "request_id": "bad"},
            {key: value for key, value in request.items() if key != "arguments"},
        )
        with patch("gway_remote.node_exec_protocol.require_account"):
            for bad in invalid:
                with self.subTest(request=bad), self.assertRaises(
                        (ValueError, PermissionError)):
                    serve_one(json.dumps(bad).encode(), hostname="gway-001")

    def test_ssh_transport_provider_read_exact_wire_without_real_ssh(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock
        from gway_remote.watchtower_exec_transport import SSHTransport

        node = SimpleNamespace(
            node="gway-001", known_hosts="/tmp/test-known-hosts",
            ssh_host_alias="gway-001", identity_file="/tmp/test-key",
            remote_user="gway-relay", wireguard_address="10.90.0.2")
        captured = []
        def fake_ssh(argv, *, input, **kwargs):
            message = json.loads(input)
            captured.append(message)
            return SimpleNamespace(stdout=json.dumps(
                {"node": "gway-001", "request_id": message["request_id"],
                 "result": {"content": []}}).encode())
        fake = Mock(side_effect=fake_ssh)
        transport = SSHTransport(node, run=fake)
        read = {**self._provider_request(tool="customer_search"),
                "operation": "provider_read"}
        self.assertEqual(transport.invoke(read)["result"], {"content": []})
        self.assertEqual(captured[0], read)
        self.assertNotIn("authorized_scope", captured[0])
        for bad in (
            {**read, "authorized_scope": "read"},
            {**read, "authorized_scope": "execute"},
            {**read, "extra": True},
            {**read, "node": "gway-002"},
            {key: value for key, value in read.items() if key != "tool"},
        ):
            with self.subTest(request=bad), self.assertRaises(ValueError):
                transport.invoke(bad)
        self.assertEqual(fake.call_count, 1)


    def test_node_lists_read_operation_support_only_when_installed(self):
        from gway_remote.mcp_node_providers import provider_list
        from gway_remote.mcp_source_registry import SourceRegistration
        from tests.helpers.mcp_federation import fixture_tool

        registration = SourceRegistration(
            source_id="odoo", revision="a" * 40,
            executable="/usr/local/bin/odoo-mcp",
            argv=("/usr/local/bin/odoo-mcp",),
            run_as="arthe", enabled=True)
        with (
            patch("gway_remote.mcp_node_providers._node_registration",
                  side_effect=lambda value: value),
            patch("gway_remote.mcp_node_providers.list_source_tools",
                  return_value=[fixture_tool("search", read=True)]),
        ):
            catalog = provider_list([registration], node_id="gway-001")
        self.assertEqual(catalog["providers"][0]["supports_provider_read"], True)

        # The older parser remains able to consume the response.
        # Old Watchtower code ignores unknown provider-level metadata.
        from gway_remote.mcp_federated_catalog import catalog_from_nodes
        _, routes = catalog_from_nodes([], {"gway-001": catalog})
        self.assertEqual(routes["odoo__search"][:4],
                         ("gway-001", "odoo", "search", "read"))

    def test_read_sender_refuses_old_receiver_without_fallback(self):
        from gway_remote.mcp_provider_transport import ProviderTransport
        from gway_remote.mcp_federated_catalog import FederationError, route_provider_call
        from types import SimpleNamespace
        from tests.helpers.mcp_provider import InvocationSpy, provider_reply
        from tests.helpers.mcp_federation import fixture_tool

        captured = []
        def send(payload):
            captured.append(dict(payload))
            return {"node": payload["node"], "request_id": payload["request_id"],
                    "result": {"content": []}}

        provider = ProviderTransport(object())
        with patch("gway_remote.mcp_provider_transport.pinned_transport",
                   return_value=SimpleNamespace(invoke=send)):
            reply = provider_reply(tools=[fixture_tool("lookup", read=True)])
            reply["providers"][0]["supports_provider_read"] = True
            routes = FederatedProviders(
                transport=InvocationSpy(response=reply),
                nodes=lambda: ("gway-001",)).discover()[1]
            route_provider_call(routes, "odoo__lookup", {},
                                authorized_scope="read", invoke=provider.invoke)
            self.assertEqual(captured[-1]["operation"], "provider_read")
            self.assertNotIn("authorized_scope", captured[-1])

            # Stage A rollback has no provider_read; fail without a remote call.
            reply["providers"][0].pop("supports_provider_read")
            routes = FederatedProviders(
                transport=InvocationSpy(response=reply),
                nodes=lambda: ("gway-001",)).discover()[1]
            with self.assertRaises(FederationError):
                route_provider_call(routes, "odoo__lookup", {},
                                    authorized_scope="read", invoke=provider.invoke)
            self.assertEqual(len(captured), 1)


if __name__ == "__main__":
    unittest.main()
