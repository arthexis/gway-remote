"""Private purpose-specific execution adapter. No public ingress yet.

The authenticated gateway/bridge must supply a verified probe principal, not
an arbitrary principal string from an RPC. Uses the pinned SSH transport and
real node worker, and a durable claim before any dispatch. No replay on crash.
"""
import re
import time
from .mcp_health_probe_contract import NODE, validate_call
from .watchtower_exec_transport import pinned_transport, SSHTransportFailure

TERMINAL = frozenset(('succeeded','failed','cancelled','timed_out','unknown'))

class ProbeExecution:
    def __init__(self, execution, *, clock=time.time):
        self.execution=execution
        self.ledger=execution.ledger
        self.clock=clock

    def _check(self, principal, *, eligibility=True):
        if type(principal) is not str or not re.fullmatch('[0-9a-f]{24}',principal):
            raise PermissionError('invalid_probe_principal')
        self.execution._allow(principal)
        if eligibility:
            self.execution._current_eligibility(NODE)
        return pinned_transport(self.execution.relay.transport,NODE).node.host_key_sha256

    @staticmethod
    def _schema(db):
        db.execute('CREATE TABLE IF NOT EXISTS health_probe_requests (request_id TEXT PRIMARY KEY, principal TEXT NOT NULL, host_key TEXT NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL, nonce_match INTEGER NOT NULL DEFAULT 0, failure_stage TEXT)')

    def start(self, principal, args):
        rid=validate_call('node_exec',args)
        host=self._check(principal)
        now=int(self.clock())
        with self.ledger.connection() as db:
            self._schema(db)
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM health_probe_requests WHERE request_id=?',(rid,)).fetchone()
            if old:
                if old['principal']!=principal or old['host_key']!=host:
                    raise PermissionError('probe_receipt_denied')
                return self._projection(old)
            if db.execute('SELECT 1 FROM requests WHERE request_id=?',(rid,)).fetchone():
                raise PermissionError('request_id_conflict')
            if db.execute('SELECT COUNT(*) FROM health_probe_requests').fetchone()[0]>=100000:
                raise RuntimeError('probe_ledger_full')
            if db.execute('SELECT 1 FROM health_probe_requests WHERE principal=? AND status NOT IN (?,?,?,?,?)',(principal,*sorted(TERMINAL))).fetchone():
                raise PermissionError('probe_in_flight')
            if db.execute('SELECT COUNT(*) FROM health_probe_requests WHERE principal=? AND created>=?',(principal,now-1800)).fetchone()[0]>=3:
                raise PermissionError('probe_rate_limit')
            db.execute('INSERT INTO health_probe_requests(request_id,principal,host_key,created,status) VALUES (?,?,?,?,?)',(rid,principal,host,now,'uncertain'))
        # Claim is committed. Exceptions leave uncertain; never resubmit.
        try:
            response=self.execution.relay.transport.invoke({'operation':'health_probe_submit','node':NODE,'request_id':rid})
        except SSHTransportFailure:
            self._failure(rid,'ssh_transport')
            return {'schema':1,'node':NODE,'request_id':rid,'status':'uncertain','nonce_match':False}
        if type(response) is not dict or response.get('node')!=NODE or response.get('request_id')!=rid:
            raise PermissionError('probe_receipt_mismatch')
        if response.get('status')=='rejected' and response.get('failure_stage')=='worker_readiness':
            self._failure(rid,'worker_readiness')
        if response.get('status')=='accepted':
            with self.ledger.connection() as db:
                db.execute("UPDATE health_probe_requests SET status='dispatched' WHERE request_id=? AND status='uncertain'",(rid,))
        return {'schema':1,'node':NODE,'request_id':rid,'status':'dispatched' if response.get('status')=='accepted' else 'uncertain','nonce_match':False}

    @staticmethod
    def _projection(row):
        return {'schema':1,'node':NODE,'request_id':row['request_id'],'status':row['status'],'nonce_match':bool(row['nonce_match'])}

    def result(self, principal, args):
        rid=validate_call('node_result',args)
        host=self._check(principal,eligibility=False)
        with self.ledger.connection() as db:
            self._schema(db)
            row=db.execute('SELECT * FROM health_probe_requests WHERE request_id=?',(rid,)).fetchone()
            if not row or row['principal']!=principal or row['host_key']!=host:
                raise PermissionError('probe_receipt_denied')
            if row['status'] in TERMINAL:
                return self._projection(row)
        value=self.execution.relay.transport.invoke({'operation':'health_probe_result','node':NODE,'request_id':rid})
        if (type(value) is not dict or set(value)!={'schema','node','request_id','status','nonce_match'} or value['schema']!=1
                or value['node']!=NODE or value['request_id']!=rid or type(value['nonce_match']) is not bool
                or value['status'] not in TERMINAL|{'queued','running'} or (value['nonce_match'] and value['status']!='succeeded')):
            raise PermissionError('invalid_probe_receipt')
        if value['status'] in TERMINAL:
            with self.ledger.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT * FROM health_probe_requests WHERE request_id=?',(rid,)).fetchone()
                if row['status'] in TERMINAL:
                    if self._projection(row)!=value: raise PermissionError('conflicting_probe_receipt')
                else:
                    db.execute('UPDATE health_probe_requests SET status=?,nonce_match=? WHERE request_id=?',(value['status'],int(value['nonce_match']),rid))
        return value


    def _failure(self, rid, stage):
        if stage not in ('ssh_transport','worker_readiness'):
            raise ValueError('invalid_probe_failure_stage')
        with self.ledger.connection() as db:
            db.execute('UPDATE health_probe_requests SET failure_stage=? WHERE request_id=? AND failure_stage IS NULL',(stage,rid))

    def diagnostic(self, principal, args):
        rid=validate_call('node_exec_diagnostic',args)
        host=self._check(principal,eligibility=False)
        with self.ledger.connection() as db:
            self._schema(db)
            row=db.execute('SELECT * FROM health_probe_requests WHERE request_id=?',(rid,)).fetchone()
            if not row or row['principal']!=principal or row['host_key']!=host:
                raise PermissionError('probe_receipt_denied')
            if row['failure_stage'] in ('ssh_transport','worker_readiness'):
                return {'request_id':rid,'status':'failure','stage':row['failure_stage']}
        return {'request_id':rid,'status':'unknown'}
