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
