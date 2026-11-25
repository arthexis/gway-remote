import json
import unittest
from unittest.mock import Mock, patch
from gway_remote import mcp_health_probe_contract as c, node_exec_protocol as p

RID='a'*32

class ProbeContractTests(unittest.TestCase):
    def args(self):
        return {'node':'gway-001','request_id':RID,'command':c.nonce_command(RID),'wait_seconds':0}

    def test_exact_start(self):
        self.assertEqual(c.validate_call('node_exec',self.args()),RID)
        for update in ({'node':'gway-004'},{'command':'true'},{'command':c.nonce_command(RID)+'; id'},{'wait_seconds':False},{'wait_seconds':1},{'extra':1}):
            with self.subTest(update=update),self.assertRaises(PermissionError):
                c.validate_call('node_exec',{**self.args(),**update})
        for bad in ('A'*32,'a'*31,'a'*32+'\n',';id'):
            with self.assertRaises(ValueError):c.nonce_command(bad)

    def test_no_other_tools_or_receipt_fields(self):
        for name in ('node_cancel','node_deploy','node_list','agentops__status'):
            with self.assertRaises(PermissionError):c.validate_call(name,{'request_id':RID})
        for name in ('node_result','node_exec_diagnostic'):
            self.assertEqual(c.validate_call(name,{'request_id':RID}),RID)
            with self.assertRaises(PermissionError):c.validate_call(name,{'request_id':RID,'cursor':0})

    @patch.object(p,'require_account')
    def test_node_constructs_command_and_rejects_raw(self,_):
        jobs=Mock(); req={'operation':'health_probe_submit','node':'gway-001','request_id':RID}
        self.assertEqual(p.serve_one(json.dumps(req).encode(),jobs=jobs,hostname='gway-001')['status'],'accepted')
        jobs.submit.assert_called_once_with('gway-001',c.nonce_command(RID),request_id=RID)
        with self.assertRaises(ValueError):p.serve_one(json.dumps({**req,'command':'id'}).encode(),jobs=jobs,hostname='gway-001')
        with self.assertRaises(PermissionError):p.serve_one(json.dumps({**req,'node':'gway-004'}).encode(),jobs=jobs,hostname='gway-004')

    @patch.object(p,'require_account')
    def test_node_projects_receipt_without_leaking_output(self,_):
        jobs=Mock(); req={'operation':'health_probe_result','node':'gway-001','request_id':RID}
        jobs.row.return_value={'node':'gway-001','command':'secret other job'}
        with self.assertRaises(PermissionError):p.serve_one(json.dumps(req).encode(),jobs=jobs,hostname='gway-001')
        jobs.result.assert_not_called()
        jobs.row.return_value['command']=c.nonce_command(RID)
        jobs.result.return_value={'schema':1,'node':'gway-001','request_id':RID,'status':'succeeded','stdout':'private output','stderr':'','exit_code':0,'truncated':False,'cursor':None}
        result=p.serve_one(json.dumps(req).encode(),jobs=jobs,hostname='gway-001')
        self.assertFalse(result['nonce_match']);self.assertNotIn('stdout',result)
        jobs.result.return_value['stdout']=RID
        self.assertTrue(p.serve_one(json.dumps(req).encode(),jobs=jobs,hostname='gway-001')['nonce_match'])


class ProbeScopeTests(unittest.TestCase):
    def test_exclusive_scope_and_no_generic_issuance(self):
        from gway_remote.mcp_bearer import BearerRegistry,BearerVerifier,SCOPES,PROBE_SCOPE
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as d:
            path=Path(d)/'registry'; registry=BearerRegistry(path)
            with self.assertRaises(ValueError): registry.issue(scope=PROBE_SCOPE,operator_approved=True)
            with self.assertRaises(PermissionError): registry.issue_health_probe()
            token=registry.issue_health_probe(operator_approved=True)
            verifier=BearerVerifier(path)
            self.assertTrue(verifier.verify(token,required_scope=PROBE_SCOPE))
            for scope in SCOPES: self.assertFalse(verifier.verify(token,required_scope=scope))
            admin=registry.issue_combined(operator_approved=True)
            self.assertFalse(verifier.verify(admin,required_scope=PROBE_SCOPE))
            with self.assertRaises(ValueError): registry.issue_oauth_pair(parent_id=token.split('_')[1],scope=PROBE_SCOPE,client_id='test')
            principal=verifier.health_probe_principal(token)
            self.assertEqual(principal,token.split('_')[1])
            self.assertTrue(registry.revoke(principal))
            self.assertFalse(verifier.verify(token,required_scope=PROBE_SCOPE))


class ProbeLedgerTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from types import SimpleNamespace
        from gway_remote.watchtower_exec_transport import RequestLedger
        from gway_remote.mcp_health_probe_execution import ProbeExecution
        d=TemporaryDirectory();self.addCleanup(d.cleanup)
        self.ledger=RequestLedger(Path(d.name)/'requests.sqlite3')
        self.transport=Mock();self.transport.node=SimpleNamespace(node='gway-001',host_key_sha256='b'*64)
        execution=Mock();execution.ledger=self.ledger;execution.relay.transport=self.transport
        self.probe=ProbeExecution(execution,clock=lambda:10000)
        self.principal='c'*24

    def start(self,rid):
        self.transport.invoke.return_value={'node':'gway-001','request_id':rid,'status':'accepted'}
        return self.probe.start(self.principal,{'node':'gway-001','command':c.nonce_command(rid),'request_id':rid,'wait_seconds':0})

    def finish(self,rid):
        self.transport.invoke.return_value={'schema':1,'node':'gway-001','request_id':rid,'status':'succeeded','nonce_match':True}
        return self.probe.result(self.principal,{'request_id':rid})

    def test_ownership_dedup_and_quota(self):
        self.start(RID);self.start(RID);self.assertEqual(self.transport.invoke.call_count,1)
        with self.assertRaises(PermissionError): self.probe.result('d'*24,{'request_id':RID})
        with self.assertRaises(PermissionError): self.start('b'*32)
        self.assertTrue(self.finish(RID)['nonce_match'])
        for rid in ('b'*32,'c'*32):self.start(rid);self.finish(rid)
        with self.assertRaises(PermissionError):self.start('d'*32)

    def test_uncertain_submission_never_replayed(self):
        args={'node':'gway-001','command':c.nonce_command(RID),'request_id':RID,'wait_seconds':0}
        self.transport.invoke.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):self.probe.start(self.principal,args)
        self.assertEqual(self.probe.start(self.principal,args)['status'],'uncertain')
        self.assertEqual(self.transport.invoke.call_count,1)


class ProbeBridgeTests(unittest.TestCase):
    def envelope(self):
        return {'version':1,'request_id':'f'*32,'principal':'c'*24,'audience':'gway-001','operation':'health_probe.start','scope':c.SCOPE,'issued_at':100,'expires_at':130,'arguments':{'node':'gway-001','command':c.nonce_command(RID),'request_id':RID,'wait_seconds':0}}

    def test_bridge_scope_is_not_interchangeable(self):
        from gway_remote.mcp_bridge_contract import validate_envelope,InvalidBridgeRequest
        e=self.envelope();self.assertEqual(validate_envelope(e,audience='gway-001',now=101),e)
        for update in ({'scope':'gway:execute'},{'operation':'execution.start'},{'arguments':{**e['arguments'],'command':'id'}}):
            with self.assertRaises(InvalidBridgeRequest):validate_envelope({**e,**update},audience='gway-001',now=101)

    def test_bridge_revalidates_dedicated_principal(self):
        from gway_remote.mcp_bridge_session import SessionBridgeDispatch
        verifier=Mock();verifier.verify.return_value=True;verifier.health_probe_principal.return_value='d'*24
        handler=SessionBridgeDispatch(verifier=verifier,session_token='test',allowed_node=lambda *a:True,read_principal=Mock(),execution=Mock())
        with patch('gway_remote.mcp_health_probe_execution.ProbeExecution') as adapter:
            with self.assertRaises(PermissionError):handler(self.envelope())
            adapter.assert_not_called()
            verifier.health_probe_principal.return_value='c'*24
            handler(self.envelope());adapter.return_value.start.assert_called_once_with('c'*24,self.envelope()['arguments'])
            verifier.verify.return_value=False
            with self.assertRaises(PermissionError):handler(self.envelope())


class ProbeIngressTests(unittest.TestCase):
    def test_restricted_http_catalog_and_no_fallthrough(self):
        from gway_remote.mcp_bearer import BearerRegistry,BearerVerifier
        from gway_remote.mcp_bearer_gateway import make_server
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from threading import Thread
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        with TemporaryDirectory() as d:
            pth=Path(d)/'registry'; token=BearerRegistry(pth).issue_health_probe(operator_approved=True)
            for enabled in (False,True):
                with make_server(('127.0.0.1',0),BearerVerifier(pth),'http://127.0.0.1:1/mcp','test',execution=Mock(),health_probe_enabled=enabled) as server:
                    th=Thread(target=server.serve_forever,daemon=True);th.start()
                    def rpc(method,params):
                        data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
                        req=Request('http://127.0.0.1:%s/mcp'%server.server_port,data,{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                        with urlopen(req,timeout=3) as r:return json.load(r)
                    try:
                        if not enabled:
                            with self.assertRaises(HTTPError) as e:rpc('tools/list',{})
                            self.assertEqual(e.exception.code,401)
                            continue
                        self.assertEqual({t['name'] for t in rpc('tools/list',{})['result']['tools']},{'node_exec','node_result','node_exec_diagnostic'})
                        for name,args in [('node_list',{}),('node_cancel',{'request_id':RID}),('node_exec',{'node':'gway-001','request_id':RID,'command':'id','wait_seconds':0})]:
                            with self.assertRaises(HTTPError) as e:rpc('tools/call',{'name':name,'arguments':args})
                            self.assertEqual(e.exception.code,403)
                    finally:server.shutdown();th.join(5)

    def test_signed_probe_bridge_does_not_fallback(self):
        from gway_remote.mcp_health_probe_ingress import dispatch
        server=Mock();server.registry.health_probe_principal.return_value='c'*24;server.bridge_transport=('/unused',b'k'*32)
        args={'node':'gway-001','request_id':RID,'command':c.nonce_command(RID),'wait_seconds':0}
        with patch('gway_remote.mcp_health_probe_ingress.call_unix',side_effect=PermissionError()),patch('gway_remote.mcp_health_probe_ingress.ProbeExecution') as direct:
            with self.assertRaises(PermissionError):dispatch(server,'test','node_exec',args)
            direct.assert_not_called()


class ProbeDiagnosticTests(ProbeLedgerTests):
    def test_typed_ssh_failure_owned_only(self):
        from gway_remote.watchtower_exec_transport import SSHTransportFailure
        self.transport.invoke.side_effect=SSHTransportFailure('private')
        args={'node':'gway-001','command':c.nonce_command(RID),'request_id':RID,'wait_seconds':0}
        self.assertEqual(self.probe.start(self.principal,args)['status'],'uncertain')
        self.assertEqual(self.probe.diagnostic(self.principal,{'request_id':RID}),{'request_id':RID,'status':'failure','stage':'ssh_transport'})
        with self.assertRaises(PermissionError):self.probe.diagnostic('d'*24,{'request_id':RID})
        self.assertEqual(self.transport.invoke.call_count,1)

    def test_generic_reservation_cannot_reuse_probe_id(self):
        from datetime import datetime,timedelta,timezone
        self.start(RID)
        with self.assertRaises(PermissionError):
            self.ledger.reserve(request_id=RID,node='gway-001',command='true',principal=self.principal,host_key_sha256='b'*64,expires_at=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat())
