"""Watchtower local timer: fixed-purpose, pinned and idle-only worker probes.

No public RPC, bearer, arbitrary commands, or new SSH credentials. The existing
execution service UID is trusted; this module is not a sandbox for that UID.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import subprocess
import time

from .periodic_health_contract import current_slot, request_id, RETENTION
from .watchtower_exec_transport import pinned_transport

ERRORS = (OSError, ValueError, RuntimeError, PermissionError, KeyError, TypeError, subprocess.SubprocessError)
TERMINAL = frozenset(('succeeded','failed','timed_out','cancelled','unknown','busy'))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS periodic_health_receipts (node TEXT NOT NULL, slot INTEGER NOT NULL, request_id TEXT UNIQUE NOT NULL, host_key_sha256 TEXT NOT NULL, state TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(node,slot))')
    db.execute('CREATE INDEX IF NOT EXISTS periodic_health_receipts_slot ON periodic_health_receipts(slot)')
    db.execute('CREATE INDEX IF NOT EXISTS periodic_health_receipts_observed ON periodic_health_receipts(updated_at)')
    db.execute('CREATE TABLE IF NOT EXISTS periodic_health_clock (singleton INTEGER PRIMARY KEY CHECK(singleton=1), slot INTEGER NOT NULL)')


def claim(ledger, node, slot, pin):
    rid = request_id(node, slot)
    with ledger.connection() as db:
        _schema(db)
        db.execute('BEGIN IMMEDIATE')
        high = db.execute('SELECT slot FROM periodic_health_clock WHERE singleton=1').fetchone()
        if high and slot < high['slot']:
            return False
        db.execute('INSERT OR REPLACE INTO periodic_health_clock VALUES (1,?)',(slot,))
        db.execute('DELETE FROM periodic_health_receipts WHERE slot < ?',(slot-RETENTION,))
        if db.execute('SELECT 1 FROM periodic_health_receipts WHERE node=? AND slot=?',(node,slot)).fetchone():
            return False
        if db.execute('SELECT COUNT(*) FROM periodic_health_receipts').fetchone()[0] >= 32*(RETENTION+1):
            raise RuntimeError('periodic health receipt capacity exceeded')
        db.execute('INSERT INTO periodic_health_receipts VALUES (?,?,?,?,?,?)',(node,slot,rid,pin,'uncertain',utcnow()))
        return True


def record(ledger, node, slot, pin, state):
    if state not in TERMINAL | {'dispatched'}:
        raise ValueError('invalid health status')
    with ledger.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE periodic_health_receipts SET state=? WHERE node=? AND slot=? AND host_key_sha256=? AND state IN ('uncertain','dispatched')", (state,node,slot,pin))


def _invoke(execution, node, pin, slot, operation):
    execution._current_eligibility(node)
    transport = pinned_transport(execution.relay.transport,node)
    if transport.node.host_key_sha256 != pin:
        raise PermissionError('pin changed')
    rid = request_id(node,slot)
    result = transport.invoke(dict(operation=operation,node=node,request_id=rid))
    if type(result) is not dict or set(result) != {'node','request_id','status'} or result['node'] != node or result['request_id'] != rid:
        raise ValueError('uncorrelated health receipt')
    return result['status']


def _result(execution,node,pin,slot):
    state = _invoke(execution,node,pin,slot,'periodic_health_result')
    if state in TERMINAL-{'busy'}:
        record(execution.ledger,node,slot,pin,state)
    elif state not in ('queued','running'):
        raise ValueError('invalid result state')
    return state


def check_node(execution, node, slot):
    """At most one submit per node/slot; reconcile a recent ambiguous receipt only."""
    try:
        execution._current_eligibility(node)
        pin = pinned_transport(execution.relay.transport,node).node.host_key_sha256
    except ERRORS:
        return 'ineligible'
    ledger = execution.ledger
    with ledger.connection() as db:
        _schema(db)
        pending = db.execute("SELECT slot FROM periodic_health_receipts WHERE node=? AND host_key_sha256=? AND slot BETWEEN ? AND ? AND state IN ('uncertain','dispatched') ORDER BY slot DESC LIMIT 1",(node,pin,slot-2,slot)).fetchone()
    if pending:
        try:
            _result(execution,node,pin,pending['slot'])
        except ERRORS:
            pass  # never resubmit the old claim
    if not claim(ledger,node,slot,pin):
        return 'already_claimed'
    try:
        state = _invoke(execution,node,pin,slot,'periodic_health_submit')
        if state in ('busy','failed'):
            record(ledger,node,slot,pin,state)
            return state
        if state != 'accepted':
            raise ValueError('invalid submit response')
        record(ledger,node,slot,pin,'dispatched')
        deadline = time.monotonic()+12
        while True:
            state = _result(execution,node,pin,slot)
            if state in TERMINAL or time.monotonic() >= deadline:
                return state
            time.sleep(0.25)
    except ERRORS:
        # Preserve claim. A later tick may read its result; never replay submit.
        return 'uncertain'


def run(execution):
    if not execution.enabled or not execution.relay.enabled:
        return {}
    transports = execution.relay.transport.transports
    if type(transports) is not dict or not 1 <= len(transports) <= 32:
        raise ValueError('invalid pinned execution targets')
    slot = current_slot()
    # Bound parallelism and use distinct node-owned admission transactions.
    def check(node):
        try:
            return node,check_node(execution,node,slot)
        except ERRORS:
            return node,'unavailable'
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(check,sorted(transports)))


def main():
    import os
    import sys
    from .watchtower_exec_service import load_service
    if len(sys.argv) != 1:
        raise SystemExit('no arguments accepted')
    os.umask(0o077)
    try:
        result = run(load_service())
    except ERRORS:
        raise SystemExit('periodic execution health unavailable') from None
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
