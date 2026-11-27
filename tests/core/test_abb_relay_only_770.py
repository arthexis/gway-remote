"""Named production relay: exact target, existing authentication, exec only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from gway_remote.node_exec_contract import validate_command, RELAY_ONLY_OPERATIONS
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
        for op in sorted(set(OPERATIONS) - RELAY_ONLY_OPERATIONS):
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
