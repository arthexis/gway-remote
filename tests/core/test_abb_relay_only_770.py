"""Named production relay: exact target, existing authentication, exec only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from gway_remote.node_exec_contract import (validate_command, RELAY_ONLY_OPERATIONS,
    ABB_PROVIDER_READ_OPERATIONS, ABB_OCPP_READ_TOOLS, abb_ocpp_registration)
from gway_remote.node_exec_protocol import serve_one, OPERATIONS
from gway_remote.watchtower_exec_transport import SSHTransport, RequestLedger

NODE = 'ocpp-abb-1'
RID = 'a' * 32


class AbbRelayTests(unittest.TestCase):
    def test_exact_named_host_contract(self):
        self.assertEqual(validate_command(NODE, 'hostname'), 'hostname')
        for node in ('ocpp-abb-2', 'gelectriic.com', 'ocpp-abb-1\n', 'watchtower'):
            with self.subTest(node=node), self.assertRaises(ValueError):
                validate_command(node, 'hostname')

    def test_node_binding_and_allowed_submit(self):
        jobs = Mock()
        raw = json.dumps(dict(operation='submit', node=NODE, request_id=RID, command='hostname')).encode()
        with patch('gway_remote.node_exec_protocol.require_account'):
            self.assertEqual(serve_one(raw, jobs=jobs, hostname=NODE)['status'], 'accepted')
            with self.assertRaises(PermissionError):
                serve_one(raw, jobs=jobs, hostname='gway-001')
        jobs.submit.assert_called_once_with(NODE, 'hostname', request_id=RID)

    def test_all_other_operations_denied_before_dispatch(self):
        for op in sorted(set(OPERATIONS) - RELAY_ONLY_OPERATIONS - ABB_PROVIDER_READ_OPERATIONS):
            with self.subTest(op=op):
                payload = {key: None for key in OPERATIONS[op]}
                payload.update(operation=op, node=NODE, request_id=RID)
                jobs = Mock()
                with patch('gway_remote.node_exec_protocol.require_account'), self.assertRaisesRegex(PermissionError, 'relay-only'):
                    serve_one(json.dumps(payload).encode(), jobs=jobs, hostname=NODE)
                self.assertFalse(jobs.mock_calls)

    def test_transport_denies_deploy_before_ssh(self):
        pinned = Mock(node=NODE)
        run = Mock()
        transport = SSHTransport(pinned, run=run)
        with self.assertRaisesRegex(PermissionError, 'relay-only'):
            transport.invoke(dict(operation='deployment_discovery', node=NODE, request_id=RID))
        run.assert_not_called()

    def test_deployment_ledger_still_rejects_abb(self):
        with TemporaryDirectory() as root:
            ledger = RequestLedger(Path(root) / 'requests.sqlite3')
            with self.assertRaisesRegex(ValueError, 'deployment node'):
                ledger.reserve_deployment(request_id=RID, node=NODE, application='ocpp_reports', revision='b'*40, principal='test', host_key_sha256='c'*64, expires_at='unused')


def _registration(*, execute=False, source="ocpp"):
    from gway_remote.mcp_source_registry import SourceRegistration
    executable = "/home/ubuntu/.local/share/ocpp-csms/releases/" + "b"*12 + "/venv/bin/ocpp-csms-mcp"
    argv = (executable, "--data-dir", "/home/ubuntu/ocpp-csms-data/schemas/8")
    return SourceRegistration(source, "b"*40, executable,
                              argv + (("--enable-execute",) if execute else ()),
                              "ubuntu", True)


def _catalog(*, node=NODE, extra=False):
    tools = [{"name": name, "description": name, "inputSchema": {"type": "object"},
              "annotations": {"readOnlyHint": True, "destructiveHint": False}}
             for name in sorted(ABB_OCPP_READ_TOOLS)]
    if extra:
        tools.append({"name": "reset", "inputSchema": {"type": "object"}})
    return {"node": node, "providers": [{"provider": "ocpp", "node": node,
            "revision": "b"*40, "status": "available",
            "supports_provider_read": True, "tools": tools}]}


class AbbReadOnlyTests(unittest.TestCase):
    def request(self, operation, **fields):
        return dict(operation=operation, node=NODE, request_id=RID, **fields)

    def test_manifest_exact_read_only(self):
        self.assertTrue(abb_ocpp_registration(_registration()))
        self.assertFalse(abb_ocpp_registration(_registration(execute=True)))
        self.assertFalse(abb_ocpp_registration(_registration(source="odoo")))

    def test_untrusted_relay_cannot_discover_or_read(self):
        for payload in (self.request("provider_list"),
                        self.request("provider_read", provider="ocpp",
                                     tool="charger_list", arguments={})):
            with patch("gway_remote.node_exec_protocol.require_account"), self.assertRaisesRegex(PermissionError, "trusted relay"):
                serve_one(json.dumps(payload).encode(), hostname=NODE)

    def test_both_boundaries_deny_all_other_providers_and_execute(self):
        for op, provider, tool in (("provider_read", "odoo", "charger_list"),
                                    ("provider_read", "ocpp", "reset"),
                                    ("provider_call", "ocpp", "charger_list")):
            payload = self.request(op, provider=provider, tool=tool, arguments={})
            run = Mock()
            with self.assertRaisesRegex(PermissionError, "relay-only"):
                SSHTransport(Mock(node=NODE), run=run).invoke(payload)
            run.assert_not_called()
            with patch("gway_remote.node_exec_protocol.require_account"), self.assertRaisesRegex(PermissionError, "relay-only"):
                serve_one(json.dumps(payload).encode(), hostname=NODE, trusted_relay=True)

    def test_node_filters_registration_before_discovery(self):
        good = _registration()
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                   return_value=(good, _registration(source="odoo"), _registration(execute=True))), \
             patch("gway_remote.mcp_node_providers.dispatch_node_provider_request",
                   return_value=_catalog()) as dispatch:
            result = serve_one(json.dumps(self.request("provider_list")).encode(),
                               hostname=NODE, trusted_relay=True)
            self.assertEqual(result["result"], _catalog())
            dispatch.assert_called_once_with((good,), {"operation": "provider_list"},
                                             node_id=NODE, trusted_scope="read")
            dispatch.return_value = _catalog(extra=True)
            with self.assertRaisesRegex(PermissionError, "catalog denied"):
                serve_one(json.dumps(self.request("provider_list")).encode(),
                          hostname=NODE, trusted_relay=True)

    def test_gateway_canonical_five_tools_no_new_alias_and_no_execute_transport(self):
        from gway_remote.mcp_federated_catalog import catalog_from_nodes, route_provider_call
        from gway_remote.mcp_node_routing import canonical_catalog
        tools, routes = catalog_from_nodes((), {"gway-001": _catalog(node="gway-001"), NODE: _catalog()})
        public, routed = canonical_catalog((), tools, routes, legacy_aliases=True)
        self.assertEqual({t["name"] for t in public}, {"ocpp__" + name for name in ABB_OCPP_READ_TOOLS})
        self.assertEqual(set(routed["ocpp__charger_list"][5]), {"gway-001", NODE})
        for scope in ("read", "execute"):
            invoke = Mock(return_value={"ok": True})
            self.assertEqual(route_provider_call(routed, "ocpp__charger_list", {"node": NODE},
                                                authorized_scope=scope, invoke=invoke), {"ok": True})
            invoke.assert_called_once_with(NODE, {"operation": "provider_read",
                "provider": "ocpp", "tool": "charger_list", "arguments": {}}, trusted_scope="read")
        tools, routes = catalog_from_nodes((), {"gway-001": _catalog(node="gway-001"),
                                               NODE: _catalog(extra=True)})
        self.assertTrue(all(r[0] != NODE for r in routes.values()))
