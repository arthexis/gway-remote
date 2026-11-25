import unittest
from unittest.mock import patch
from gway_remote import probe_provision as p

class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.state={'parent_id':'a'*24,'parent_expires_at':1000,'access_token':'synthetic','refresh_token':'synthetic'}
        self.receipt={'configured':True,'parent_id':'a'*24,'parent_expires_at':1000,'refresh_state':'ready'}
        self.current={'configured':False};self.calls=[];self.fail=None
    def invoke(self,account,action,payload):
        self.calls.append(action)
        if action=='status':return self.current
        if action=='issue':return self.state
        if action=='verify':return {'valid':True,'parent_expires_at':1000}
        if action=='revoke':return {'revoked':True}
        if action=='install':
            if self.fail=='before':raise TimeoutError()
            self.current=self.receipt
            if self.fail=='after':raise TimeoutError()
            return self.receipt
        raise AssertionError(action)
    def test_success_and_idempotence(self):
        result=p.provision(30,invoke=self.invoke)
        self.assertEqual(result['delivery'],'verified');self.assertNotIn('access_token',result)
        self.assertFalse(result['recovery_enabled_by_command'])
        self.assertEqual(p.provision(30,invoke=self.invoke),result)
        self.assertEqual(self.calls.count('issue'),1)
    def test_ack_lost_after_install(self):
        self.fail='after';self.assertEqual(p.provision(30,invoke=self.invoke)['delivery'],'verified');self.assertNotIn('revoke',self.calls)
    def test_failure_before_install_revokes(self):
        self.fail='before'
        with self.assertRaises(PermissionError):p.provision(30,invoke=self.invoke)
        self.assertEqual(self.calls[-1],'revoke')
    def test_existing_uncertain_refuses(self):
        self.current={**self.receipt,'refresh_state':'uncertain'}
        with self.assertRaises(PermissionError):p.provision(30,invoke=self.invoke)
        self.assertNotIn('issue',self.calls)
    def test_console_requires_tty(self):
        with patch.object(p.os,'geteuid',return_value=0),patch.object(p.sys.stdin,'isatty',return_value=False),patch.object(p,'provision') as run:
            self.assertEqual(p.main(['gway-001']),1);run.assert_not_called()

    def test_pinned_relay_is_transport_not_executor(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        transport=Mock();transport.node.remote_user='gway-relay'
        def invoke(payload):return {'node':'gway-001','request_id':payload['request_id'],'result':{'configured':False}}
        transport.invoke.side_effect=invoke
        service=Mock()
        with patch.object(p.os,'geteuid',return_value=123),patch.object(p.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=123)),patch('gway_remote.watchtower_exec_service.load_service',return_value=service),patch('gway_remote.watchtower_exec_transport.pinned_transport',return_value=transport):
            self.assertEqual(p.internal('status',{}),{'configured':False})
            service._current_eligibility.assert_called_once_with('gway-001')
            transport.node.remote_user='gway-exec'
            with self.assertRaises(PermissionError):p.internal('status',{})

    def test_stage_error_never_contains_private_exception(self):
        with patch.object(p,'_child',side_effect=RuntimeError('secret value')):
            with self.assertRaises(p.ProvisionStageError) as err:p.child(p.GATEWAY,'status',{})
        self.assertEqual(err.exception.stage,'status');self.assertNotIn('secret',str(err.exception))

    def test_node_requires_installation_executor(self):
        import json
        from gway_remote import node_exec_protocol as protocol
        raw=json.dumps({'operation':'probe_provision_status','node':'gway-001','request_id':'a'*32}).encode()
        with patch.object(protocol,'require_account'),patch('gway_remote.node_exec_identity.selected_user',return_value='gway-exec'),patch('gway_remote.probe_provision_node.deliver') as deliver:
            with self.assertRaises(PermissionError):protocol.serve_one(raw,hostname='gway-001')
            deliver.assert_not_called()
        with patch.object(protocol,'require_account'),patch('gway_remote.node_exec_identity.selected_user',return_value='arthe'),patch('gway_remote.probe_provision_node.deliver',return_value={'configured':False}):
            self.assertEqual(protocol.serve_one(raw,hostname='gway-001')['result'],{'configured':False})
