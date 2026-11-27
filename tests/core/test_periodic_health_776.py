"""Idle-only admission and durable purpose separation for recurring probes."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gway_remote.node_exec_worker import Jobs
from gway_remote.node_exec_protocol import serve_one
from gway_remote.periodic_health_contract import COMMAND, current_slot, request_id, validate_probe
from gway_remote.periodic_execution_health import check_node, run, claim, record
from gway_remote.watchtower_exec_transport import RequestLedger, MultiNodeTransport, SSHTransport
from gway_remote.execution_health import recent_probes

NODE='ocpp-abb-1'
PIN='a'*64

class PeriodicReceiverTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.jobs=Jobs(Path(tmp.name)/'jobs.sqlite3',max_active=3)
        self.slot=current_slot(); self.rid=request_id(NODE,self.slot)
        self.launch=Mock()
        for name,value in [('require_account',None),('selected_user','ubuntu'),('user_manager_env',{})]:
            p=patch('gway_remote.node_exec_worker.'+name,return_value=value); p.start(); self.addCleanup(p.stop)

    def probe(self):
        return self.jobs.submit(NODE,COMMAND,request_id=self.rid,periodic_slot=self.slot,execute=self.launch)

    def test_busy_even_when_capacity_available(self):
        self.jobs.submit(NODE,'true',request_id='a'*32,execute=self.launch)
        with self.assertRaisesRegex(RuntimeError,'executor busy'):
            self.probe()
        self.assertEqual(self.launch.call_count,1)
        with self.jobs.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM periodic_health_jobs').fetchone()[0],0)

    def test_idempotent_and_exact_hostname_result(self):
        self.probe(); self.probe()
        self.assertEqual(self.launch.call_count,1)
        with self.jobs.connection() as db:
            db.execute("UPDATE jobs SET status='succeeded',exit_code=0,output=? WHERE id=?",(b'wrong\n',self.rid))
        self.assertEqual(self.jobs.periodic_result(NODE,self.rid)['status'],'failed')
        with self.jobs.connection() as db:
            db.execute('UPDATE jobs SET output=? WHERE id=?',((NODE+'\n').encode(),self.rid))
        self.assertEqual(self.jobs.periodic_result(NODE,self.rid)['status'],'succeeded')

    def test_scope_rejects_caller_command_and_old_slot(self):
        with self.assertRaises(PermissionError):
            self.jobs.submit(NODE,'id',request_id=self.rid,periodic_slot=self.slot,execute=self.launch)
        with self.assertRaises(PermissionError):
            self.jobs.submit(NODE,COMMAND,request_id=self.rid,execute=self.launch)
        with self.assertRaises(PermissionError):
            validate_probe(NODE,request_id(NODE,self.slot-2),submit=True)
        self.launch.assert_not_called()

    def test_protocol_only_fixed_fields_and_sanitized_busy(self):
        jobs=Mock(); jobs.submit.side_effect=RuntimeError('executor busy')
        payload=dict(operation='periodic_health_submit',node=NODE,request_id=self.rid)
        with patch('gway_remote.node_exec_protocol.require_account'):
            self.assertEqual(serve_one(json.dumps(payload).encode(),jobs=jobs,hostname=NODE)['status'],'busy')
            with self.assertRaises(ValueError):
                serve_one(json.dumps(dict(payload,command='true')).encode(),jobs=jobs,hostname=NODE)
            with self.assertRaises(PermissionError):
                serve_one(json.dumps(payload).encode(),jobs=jobs,hostname='gway-001')
        jobs.submit.assert_called_once_with(NODE,COMMAND,request_id=self.rid,periodic_slot=self.slot)

    def test_periodic_retention_preserves_ordinary_receipts(self):
        oldslot=self.slot-10; old=request_id(NODE,oldslot)
        with self.jobs.connection() as db:
            for rid,command in [(old,COMMAND),('b'*32,'true')]:
                db.execute("INSERT INTO jobs(id,node,command,status,created_at) VALUES(?,?,?,'succeeded','2020-01-01')",(rid,NODE,command))
            db.execute('INSERT INTO periodic_health_jobs VALUES(?,?)',(old,oldslot))
        self.probe()
        with self.jobs.connection() as db:
            self.assertEqual(db.execute('SELECT id FROM jobs ORDER BY id').fetchall()[0][0],self.rid)
            self.assertIsNotNone(db.execute('SELECT 1 FROM jobs WHERE id=?',('b'*32,)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM jobs WHERE id=?',(old,)).fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM job_tombstones').fetchone()[0],0)

class PeriodicWatchtowerTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.ledger=RequestLedger(Path(tmp.name)/'requests.sqlite3')
        self.slot=current_slot()
        self.transport=Mock(); self.transport.node=SimpleNamespace(node=NODE,host_key_sha256=PIN)
        self.exec=Mock(); self.exec.enabled=True; self.exec.relay.enabled=True
        self.exec.relay.transport=MultiNodeTransport({NODE:self.transport}); self.exec.ledger=self.ledger
        self.transport.invoke.side_effect=lambda p: dict(node=p['node'],request_id=p['request_id'],status='accepted' if p['operation'].endswith('submit') else 'succeeded')

    def test_success_and_no_replay_or_ordinary_ledger_growth(self):
        self.assertEqual(check_node(self.exec,NODE,self.slot),'succeeded')
        self.assertEqual(check_node(self.exec,NODE,self.slot),'already_claimed')
        self.assertEqual(self.transport.invoke.call_count,2)
        self.assertEqual(recent_probes(self.exec)[NODE]['execution_health'],'verified')
        with self.ledger.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM periodic_health_receipts').fetchone()[0],1)

    def test_revoked_no_dispatch(self):
        self.exec._current_eligibility.side_effect=PermissionError('revoked')
        self.assertEqual(check_node(self.exec,NODE,self.slot),'ineligible')
        self.transport.invoke.assert_not_called()

    def test_uncertain_receipt_reconciles_read_only(self):
        self.transport.invoke.side_effect=OSError('transport unavailable')
        self.assertEqual(check_node(self.exec,NODE,self.slot),'uncertain')
        self.transport.invoke.reset_mock()
        self.transport.invoke.side_effect=lambda p:dict(node=p['node'],request_id=p['request_id'],status='succeeded')
        self.assertEqual(check_node(self.exec,NODE,self.slot),'already_claimed')
        self.assertEqual(self.transport.invoke.call_args.args[0]['operation'],'periodic_health_result')
        self.assertEqual(recent_probes(self.exec)[NODE]['execution_health'],'verified')

    def test_busy_preserves_previous_fresh_health(self):
        check_node(self.exec,NODE,self.slot)
        self.transport.invoke.side_effect=lambda p:dict(node=p['node'],request_id=p['request_id'],status='busy')
        self.assertEqual(check_node(self.exec,NODE,self.slot+1),'busy')
        self.assertEqual(recent_probes(self.exec)[NODE]['execution_health'],'verified')

    def test_bad_receipt_and_changed_pin_never_verify(self):
        self.transport.invoke.side_effect=lambda p:dict(node='gway-002',request_id=p['request_id'],status='accepted')
        self.assertEqual(check_node(self.exec,NODE,self.slot),'uncertain')
        self.assertEqual(recent_probes(self.exec)[NODE]['execution_health'],'unverified')
        self.transport.node.host_key_sha256='b'*64
        self.assertNotIn(NODE,recent_probes(self.exec))
        self.assertEqual(check_node(self.exec,NODE,self.slot),'already_claimed')

    def test_retention_and_clock_regression(self):
        old=self.slot-3000
        self.assertTrue(claim(self.ledger,NODE,old,PIN))
        record(self.ledger,NODE,old,PIN,'succeeded')
        self.assertTrue(claim(self.ledger,NODE,self.slot,PIN))
        self.assertFalse(claim(self.ledger,NODE,old,PIN))
        with self.ledger.connection() as db:
            self.assertEqual(db.execute('SELECT slot FROM periodic_health_receipts').fetchone()[0],self.slot)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],0)

    def test_transport_rejects_extra_command_before_ssh(self):
        launch=Mock(); transport=SSHTransport(self.transport.node,run=launch)
        with self.assertRaises(ValueError):
            transport.invoke(dict(operation='periodic_health_submit',node=NODE,request_id=request_id(NODE,self.slot),command='true'))
        launch.assert_not_called()

    def test_parallel_pinned_targets_dynamic_and_no_general_exec(self):
        names=['gway-001','gway-002','gway-004','gway-005',NODE]
        transports={}
        for node in names:
            t=Mock(); t.node=SimpleNamespace(node=node,host_key_sha256=PIN)
            t.invoke.side_effect=lambda p:dict(node=p['node'],request_id=p['request_id'],status='accepted' if p['operation'].endswith('submit') else 'succeeded')
            transports[node]=t
        self.exec.relay.transport=MultiNodeTransport(transports)
        self.assertEqual(run(self.exec),dict.fromkeys(names,'succeeded'))
        self.assertEqual(set(recent_probes(self.exec)),set(names))
        self.exec.exec.assert_not_called()
        for transport in transports.values():
            self.assertEqual([call.args[0]['operation'] for call in transport.invoke.call_args_list],['periodic_health_submit','periodic_health_result'])
