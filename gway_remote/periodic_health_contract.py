"""Private fixed-purpose health protocol; no caller-controlled command."""
import hashlib
import time

INTERVAL = 300
RETENTION = 7 * 24 * 60 * 60 // INTERVAL
NODE_RETENTION = 6
COMMAND = '/bin/hostname'
OPERATIONS = frozenset(('periodic_health_submit', 'periodic_health_result'))


def current_slot():
    return int(time.time()) // INTERVAL


def request_id(node, slot):
    from .node_exec_contract import validate_command
    validate_command(node, COMMAND)
    if type(slot) is not int or not 0 <= slot < 2**48:
        raise ValueError('invalid probe slot')
    digest = hashlib.sha256(('gway-periodic-health-v1:'+node+':'+str(slot)).encode()).hexdigest()
    return f'{slot:012x}'+digest[:20]


def slot_for(node, rid):
    if type(rid) is not str or len(rid) != 32:
        return None
    try:
        slot = int(rid[:12], 16)
        return slot if request_id(node, slot) == rid else None
    except ValueError:
        return None


def validate_probe(node, rid, *, submit):
    slot = slot_for(node, rid)
    now = current_slot()
    # Permit one boundary-crossing slot. Expired submissions can never replay.
    if slot is None or not now-(1 if submit else NODE_RETENTION) <= slot <= now:
        raise PermissionError('invalid or expired periodic probe')
    return slot
