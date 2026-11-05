import unittest
from unittest.mock import Mock, patch
from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.mcp_bearer_gateway import EXEC_TOOLS


class InlineExecTests(unittest.TestCase):
    def test_schema_exposes_optional_wait(self):
        tool = next(x for x in EXEC_TOOLS if x['name'] == 'node_exec')
        prop = tool['inputSchema']['properties']['wait_seconds']
        self.assertEqual((prop['minimum'], prop['maximum']), (0, 10))
        self.assertNotIn('wait_seconds', tool['inputSchema']['required'])

    def test_inline_returns_terminal_result(self):
        service = Mock(spec=AuthorizedExecution)
        service._allow.return_value = None
        service._current_eligibility.return_value = None
        relay = Mock()
        relay.transport.node.node = 'gway-001'
        relay.transport.node.host_key_sha256 = 'a' * 64
        relay.dispatch.return_value = 'dispatched'
        relay.result.return_value = {'status': 'succeeded', 'stdout': 'ok', 'exit_code': 0}
        ledger = Mock()
        ledger.get.side_effect = ValueError('request not found')
        service = AuthorizedExecution(ledger, None, relay, enabled=True)
        with patch.object(service, '_allow'), patch.object(service, '_current_eligibility'), patch.object(ledger, 'reserve'):
            result = service.exec(principal='owner', request_id='b'*32, node='gway-001', command='uptime')
        self.assertEqual(result['stdout'], 'ok')
        relay.result.assert_called_once()

    def test_async_opt_out(self):
        relay = Mock()
        relay.transport.node.node = 'gway-001'
        relay.transport.node.host_key_sha256 = 'a'*64
        relay.dispatch.return_value = 'dispatched'
        ledger = Mock()
        ledger.get.side_effect = ValueError('request not found')
        service = AuthorizedExecution(ledger, None, relay, enabled=True)
        with patch.object(service, '_allow'), patch.object(service, '_current_eligibility'), patch.object(ledger, 'reserve'):
            result = service.exec(principal='owner', request_id='b'*32, node='gway-001', command='uptime', wait_seconds=0)
        self.assertEqual(result['status'], 'dispatched')
        relay.result.assert_not_called()
