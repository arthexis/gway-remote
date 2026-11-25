"""The external probe reports only fixed classes, never secrets or node data."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

path = Path(__file__).resolve().parents[2] / 'scripts/mcp-external-health.py'
spec = importlib.util.spec_from_file_location('mcp_external_health_690', path)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class Response(io.BytesIO):
    status = 200


class ExternalHealthTests(unittest.TestCase):
    def state(self, expires=9999):
        return {'client_id': 'observer-client', 'access_token': 'access-private',
                'refresh_token': 'refresh-private', 'expires_at': expires,
                'refresh_state': 'ready', 'parent_expires_at': 9999999}

    def test_private_credential_file_and_symlink_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            credential = folder / 'token'
            credential.write_text(json.dumps(self.state()))
            credential.chmod(0o600)
            self.assertEqual(health.access_token(credential, now=lambda: 1000), 'access-private')
            credential.chmod(0o644)
            with self.assertRaises(ValueError):
                health.access_token(credential)
            credential.chmod(0o600)
            link = folder / 'link'
            link.symlink_to(credential)
            with self.assertRaises(OSError):
                health.access_token(link)
            folder.chmod(0o777)
            with self.assertRaises(ValueError):
                health.access_token(credential)

    def test_rotation_persists_new_pair_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential = Path(tmp) / 'oauth.json'
            credential.write_text(json.dumps(self.state(expires=1000)))
            credential.chmod(0o600)
            payload = {'scope': 'gway:read', 'token_type': 'Bearer', 'expires_in': 3600,
                       'access_token': 'new-access', 'refresh_token': 'new-refresh'}
            token = health.access_token(credential, now=lambda: 1000,
                opener=lambda *a, **kw: Response(json.dumps(payload).encode()))
            self.assertEqual(token, 'new-access')
            stored = json.loads(credential.read_text())
            self.assertEqual(stored['refresh_token'], 'new-refresh')
            self.assertEqual(stored['refresh_state'], 'ready')
            self.assertEqual(credential.stat().st_mode & 0o777, 0o600)

    def test_uncertain_refresh_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential = Path(tmp) / 'oauth.json'
            credential.write_text(json.dumps(self.state(expires=1000)))
            credential.chmod(0o600)
            calls = []
            def unavailable(*args, **kwargs):
                calls.append(1)
                raise TimeoutError('private exception')
            for _ in range(2):
                with self.assertRaises(health.RefreshUncertain):
                    health.access_token(credential, now=lambda: 1000, opener=unavailable)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(credential.read_text())['refresh_state'], 'uncertain')

    def test_refresh_with_broader_scope_is_rejected_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential = Path(tmp) / 'oauth.json'
            credential.write_text(json.dumps(self.state(expires=1000)))
            credential.chmod(0o600)
            payload = {'scope': 'gway:execute', 'token_type': 'Bearer', 'expires_in': 3600,
                       'access_token': 'bad-access', 'refresh_token': 'bad-refresh'}
            with self.assertRaises(health.RefreshUncertain):
                health.access_token(credential, now=lambda: 1000,
                    opener=lambda *a, **kw: Response(json.dumps(payload).encode()))
            self.assertEqual(json.loads(credential.read_text())['refresh_state'], 'uncertain')

    def test_expiring_parent_never_reports_healthy(self):
        with patch.object(health, 'access_token', return_value='private'), \
             patch.object(health, 'probe', return_value='ok'), \
             patch.object(health, '_read_state', return_value={'parent_expires_at': 1001}), \
             patch.object(health.time, 'time', return_value=1000), \
             patch('builtins.print') as report:
            self.assertEqual(health.main(), 1)
            self.assertEqual(json.loads(report.call_args.args[0])['status'], 'credential_expiring')

    def test_authenticated_node_list(self):
        seen = []
        def open_request(request, timeout):
            seen.append((request.get_method(), json.loads(request.data), timeout))
            response = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [
                {'type': 'text', 'text': json.dumps({'schema': 1, 'nodes': [],
                                                    'watchtower_monitor': {'status': 'ok'}})}]}}
            return Response(json.dumps(response).encode())
        self.assertEqual(health.probe('private-token', opener=open_request), 'ok')
        self.assertEqual(seen[0][1]['params']['name'], 'node_list')
        self.assertNotIn('private-token', repr(seen))

    def test_watchtower_monitor_failure_and_unknown_fail_the_external_check(self):
        for status, expected in (('failed', 'watchtower_monitor_failed'),
                                 ('unknown', 'watchtower_monitor_unavailable')):
            response = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [
                {'type': 'text', 'text': json.dumps({'schema': 1, 'nodes': [],
                                                    'watchtower_monitor': {'status': status}})}]}}
            with self.subTest(status=status):
                self.assertEqual(health.probe('private-token', opener=lambda *a, **kw:
                    Response(json.dumps(response).encode())), expected)

    def test_missing_watchtower_projection_does_not_claim_healthy(self):
        response = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [
            {'type': 'text', 'text': json.dumps({'schema': 1, 'nodes': []})}]}}
        self.assertEqual(health.probe('private-token', opener=lambda *a, **kw:
            Response(json.dumps(response).encode())), 'watchtower_monitor_unavailable')

    def test_http_auth_and_tool_errors_are_distinct(self):
        def denied(*args, **kwargs):
            raise HTTPError('private-url', 401, 'private', {}, None)
        self.assertEqual(health.probe('private-token', opener=denied), 'authentication_failed')
        self.assertEqual(health.probe('private-token', opener=lambda *a, **kw:
            Response(b'{"id":1,"result":{"isError":true}}')), 'tool_failed')


class ExtendedHealthTests(unittest.TestCase):
    def test_fixed_calls_and_no_secrets_in_report(self):
        seen=[]
        names=['agentops__daily_health_status','agentops__status','android__status']
        def open_request(request, timeout):
            doc=json.loads(request.data)
            if not request.has_header('Authorization'):
                raise HTTPError('private-url',401,'private',{},None)
            method=doc['method']; params=doc['params']
            seen.append((method,params))
            if method=='initialize':
                result={'protocolVersion':'2025-03-26'}
            elif method=='tools/list':
                result={'tools':[{'name':n,'inputSchema':{'properties':{'node':{}}}} for n in names]}
            else:
                name=params['name']
                payload={'tools':[{'name':n,'required_scope':'gway:read','nodes':['gway-001','gway-004'] if n=='agentops__status' else ['gway-001']} for n in names]} if name=='mcp_catalog_inspect' else {'schedule':{'id':'gway-001-daily-health'}} if name==names[0] else {'node':'gway-001','status':'preview_only','authorization':{'required_scope':'gway:execute'}} if name=='node_exec_preview' else {'private':'never-publish'}
                result={'content':[{'type':'text','text':json.dumps(payload)}]}
            return Response(json.dumps({'id':1,'result':result}).encode())
        report=health.extended_probe('private-token',opener=open_request)
        self.assertEqual(report,{'anonymous':'denied','read':'ok','optional_failures':0,'optional_checked':3})
        self.assertIn(('tools/call',{'name':'agentops__status','arguments':{'node':'gway-004'}}),seen)
        self.assertNotIn('private',repr(report))

    def test_projection_caches_healthy_but_not_failure_or_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'status.json'; calls=[]
            def healthy(token):
                calls.append(1)
                return {'anonymous':'denied','read':'ok','optional_failures':0,'optional_checked':3}
            health.publish_extended('private',path=path,now=lambda:1000,probe=healthy)
            health.publish_extended('private',path=path,now=lambda:1100,probe=healthy)
            self.assertEqual(len(calls),1)
            health.publish_extended(None,base_status='credential_unavailable',path=path,now=lambda:1200,probe=healthy)
            self.assertEqual(json.loads(path.read_text())['read'],'authorization')
            self.assertEqual(path.stat().st_mode&0o777,0o644)
            health.publish_extended('private',path=path,now=lambda:1300,probe=healthy)
            self.assertEqual(len(calls),2)


class FederatedEnvelopeTests(unittest.TestCase):
    @staticmethod
    def wrap(payload, **extra):
        return {'content':[{'type':'text','text':json.dumps(payload)}],**extra}

    def test_builtin_and_federated(self):
        payload={'schedule':{'id':'gway-001-daily-health'}}
        self.assertEqual(health.decode_tool_result(self.wrap(payload)),payload)
        self.assertEqual(health.decode_tool_result(self.wrap(self.wrap(payload))),payload)

    def test_reject_nested_error_and_third_envelope(self):
        for v in (self.wrap(self.wrap({},isError=True)),self.wrap(self.wrap(self.wrap({}))),self.wrap({'error':'private'}),{'content':[]}):
            with self.subTest():
                with self.assertRaises(ValueError):
                    health.decode_tool_result(v)


class ExecutionProjectionTests(unittest.TestCase):
    def test_pending_nonce_is_reconciled_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'status.json';token=root/'probe-oauth.json'
            state={'client_id':'gway-health-probe-001','access_token':'gwr_'+'a'*24+'_'+'b'*43,'refresh_token':'gwf_'+'a'*24+'_'+'c'*43,'parent_id':'d'*24,'parent_expires_at':99999,'expires_at':9999,'refresh_state':'ready'}
            health._write_state(token,state);calls=[]
            def probe(secret,*,rid,submit):
                calls.append((rid,submit));return ('exec_infra_failure','ssh_transport',False) if submit else ('ok',None,True)
            for stamp in (1000,1100,2000):
                health.publish_execution(path=path,token_path=token,now=lambda:stamp,get_token=lambda *a,**kw:'private',probe=probe,catalog=lambda _:None)
            self.assertEqual(len(calls),2);self.assertEqual(calls[0][0],calls[1][0]);self.assertEqual([x[1] for x in calls],[True,False])
            self.assertFalse((root/'probe-pending.json').exists());self.assertEqual(json.loads(path.read_text())['execute'],'ok');self.assertNotIn(calls[0][0],path.read_text())


class ProbeInstallDeliveryTests(unittest.TestCase):
    def test_fixed_install_private_and_no_replace(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'probe-oauth.json';now=int(time.time())
            state={'client_id':'gway-health-probe-001','access_token':'gwr_'+'a'*24+'_'+'b'*43,'refresh_token':'gwf_'+'a'*24+'_'+'c'*43,'parent_id':'d'*24,'parent_expires_at':now+86400,'expires_at':now+3600,'refresh_state':'ready'}
            self.assertEqual(health.probe_install_status(path),{'configured':False})
            receipt=health.install_probe_state(state,path)
            self.assertEqual(receipt['parent_id'],state['parent_id'])
            self.assertNotIn('access_token',receipt);self.assertNotIn('refresh_token',receipt)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(PermissionError):health.install_probe_state(state,path)
            self.assertEqual(json.loads(path.read_text()),state)

    def test_pending_identity_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'probe-oauth.json';(path.parent/'probe-pending.json').write_text('{}')
            with self.assertRaises(PermissionError):health.probe_install_status(path)
