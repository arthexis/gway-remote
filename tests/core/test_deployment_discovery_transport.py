"""Discovery and alias behavior at the authenticated node boundaries."""
import json
import unittest
from unittest.mock import patch

from gway_remote import node_exec_protocol
from gway_remote.mcp_bridge_gateway_dispatch import OPERATIONS
from gway_remote.mcp_bearer_gateway import NODE_TOOLS, EXEC_TOOL_NAMES
from gway_remote.watchtower_exec_auth import AuthorizedExecution


class DeploymentDiscoveryTests(unittest.TestCase):
    def setUp(self):
        class Service(AuthorizedExecution):
            def _allow_preview_eligibility(self, node):
                if node != 'gway-001':
                    raise PermissionError('denied')
        self.service = Service(None, None, type('Relay', (), {'transport': object()})())

    def test_node_discovery_is_read_only_and_bound(self):
        rows = [{'application': 'lcd_sound', 'alias': 'gway-lcd-sound',
                 'revision': 'a' * 40, 'status': 'declared'}]
        request = {'node': 'gway-001', 'request_id': 'b' * 32, 'operation': 'deployment_discovery'}
        with patch.object(node_exec_protocol, 'require_account'), patch(
                'gway_remote.mcp_deployment_resolver.deployment_catalog', return_value=rows):
            result = node_exec_protocol.serve_one(json.dumps(request).encode(), hostname='gway-001')
        self.assertEqual(result, {'node': 'gway-001', 'request_id': 'b' * 32, 'result': rows})
        self.assertEqual(OPERATIONS['node_deploy_discovery'], ('deployment.discovery', 'gway:read'))
        self.assertNotIn('node_deploy_discovery', EXEC_TOOL_NAMES)
        self.assertTrue(next(x for x in NODE_TOOLS if x['name'] == 'node_deploy_discovery')['annotations']['readOnlyHint'])

    def test_discovery_validates_node_response_and_rejects_extra_paths(self):
        class Pinned:
            def invoke(self, request):
                return {'node': request['node'], 'request_id': request['request_id'], 'result': [
                    {'application': 'lcd_sound', 'alias': 'gway-lcd-sound',
                     'revision': 'a' * 40, 'status': 'declared'}]}
        pin = Pinned()
        with patch('gway_remote.watchtower_exec_auth.pinned_transport', return_value=pin):
            self.assertEqual(self.service.deployment_discovery(node='gway-001')['applications'][0]['application'], 'lcd_sound')
            original = pin.invoke
            def bad(request):
                response = original(request)
                response['result'][0]['runner'] = '/private/path'
                return response
            pin.invoke = bad
            with self.assertRaises(PermissionError):
                self.service.deployment_discovery(node='gway-001')

    def test_alias_is_normalized_before_preview_and_request_binding(self):
        class Pinned:
            def invoke(self, request):
                self.request = request
                return {'node': request['node'], 'request_id': request['request_id'],
                        'result': {'application': request['application'], 'revision': 'a' * 40, 'status': 'declared'}}
        pin = Pinned()
        with patch('gway_remote.watchtower_exec_auth.pinned_transport', return_value=pin):
            alias = self.service.deployment_preview(node='gway-001', application='gway-lcd-sound')
            canonical = self.service.deployment_preview(node='gway-001', application='lcd_sound')
            self.assertEqual(alias, canonical)
            self.assertEqual(pin.request['application'], 'lcd_sound')
        with patch.object(self.service, '_allow'), patch.object(self.service, '_current_eligibility'), patch.object(self.service, 'ledger') as ledger:
            ledger.get.side_effect = ValueError('request not found')
            with self.assertRaises(ValueError):
                self.service.deployment(principal='p', request_id='b' * 32, node='gway-001', application='gway-agent-ops', status=True)
            ledger.get.assert_called_once_with('b' * 32)

    def test_node_returns_only_allowlisted_error(self):
        request = {'node': 'gway-001', 'request_id': 'b' * 32,
                   'operation': 'deployment_preview', 'application': 'lcd_sound'}
        with patch.object(node_exec_protocol, 'require_account'), patch(
                'gway_remote.mcp_deployment_broker.preview', side_effect=PermissionError('deployment_no_declaration')):
            response = node_exec_protocol.serve_one(json.dumps(request).encode(), hostname='gway-001')
        self.assertEqual(response['error'], 'deployment_no_declaration')

    def test_discovery_registry_error_is_correlated_and_sanitized(self):
        request = {'node': 'gway-001', 'request_id': 'b' * 32,
                   'operation': 'deployment_discovery'}
        with patch.object(node_exec_protocol, 'require_account'), patch(
                'gway_remote.mcp_deployment_resolver.deployment_catalog',
                side_effect=PermissionError('/private/manifest')):
            response = node_exec_protocol.serve_one(json.dumps(request).encode(), hostname='gway-001')
        self.assertEqual(response, {'node': 'gway-001', 'request_id': 'b' * 32,
                                    'error': 'deployment_declaration_invalid'})
        class Pinned:
            def invoke(self, req):
                return {'node': req['node'], 'request_id': req['request_id'],
                        'error': 'deployment_declaration_invalid'}
        with patch('gway_remote.watchtower_exec_auth.pinned_transport', return_value=Pinned()):
            with self.assertRaisesRegex(PermissionError, '^deployment_declaration_invalid$'):
                self.service.deployment_discovery(node='gway-001')

    def test_discovery_transport_error_does_not_leak_details(self):
        class Pinned:
            def invoke(self, request):
                raise OSError('/private/ssh/key')
        with patch('gway_remote.watchtower_exec_auth.pinned_transport', return_value=Pinned()):
            with self.assertRaisesRegex(PermissionError, '^deployment_ssh_unverified$'):
                self.service.deployment_discovery(node='gway-001')

    def test_run_and_status_errors_are_correlated_and_sanitized(self):
        for op, method, message, expected in (
                ("deployment_run", "accept", "deployment revision changed since preview", "deployment_declaration_drift"),
                ("deployment_status", "request_status", "deployment request not found", "deployment_request_not_found"),
                ("deployment_status", "request_status", "/private/receipt", "deployment_permission_denied")):
            request = {"node": "gway-001", "request_id": "b"*32, "operation": op, "application": "lcd_sound"}
            if op == "deployment_run":
                request["expected_revision"] = "a"*40
            with patch.object(node_exec_protocol, "require_account"), patch(
                    "gway_remote.mcp_deployment_broker."+method, side_effect=PermissionError(message)):
                result = node_exec_protocol.serve_one(json.dumps(request).encode(), hostname="gway-001")
            self.assertEqual(result, {"node": "gway-001", "request_id": "b"*32, "error": expected})
