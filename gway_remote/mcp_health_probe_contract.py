"""Exclusive-purpose health probe contract; no general execution authority."""
import re

SCOPE = 'gway:health-probe'
NODE = 'gway-001'
NONCE = re.compile(r'[0-9a-f]{32}', re.ASCII)
START = 'node_exec'
READS = frozenset(('node_result', 'node_exec_diagnostic'))


def nonce_command(request_id):
    if type(request_id) is not str or not NONCE.fullmatch(request_id):
        raise ValueError('invalid_probe_nonce')
    return 'printf %s ' + request_id


def validate_call(name, args):
    if type(args) is not dict or name not in (START, *READS):
        raise PermissionError('probe_operation_denied')
    rid = args.get('request_id')
    command = nonce_command(rid)
    if name == START:
        if (set(args) != {'node','request_id','command','wait_seconds'}
                or args['node'] != NODE or args['command'] != command
                or type(args['wait_seconds']) is not int or args['wait_seconds'] != 0):
            raise PermissionError('probe_arguments_denied')
    elif set(args) != {'request_id'}:
        raise PermissionError('probe_arguments_denied')
    return rid


def project_result(result, rid):
    """Project only fixed values; never return arbitrary job output."""
    nonce_command(rid)
    if (type(result) is not dict or result.get('node') != NODE or result.get('request_id') != rid):
        raise PermissionError('probe_receipt_mismatch')
    status = result.get('status')
    if status not in ('accepted','queued','running','dispatched','succeeded','failed','cancelled','timed_out','unknown','uncertain'):
        raise ValueError('invalid_probe_status')
    matched = (status == 'succeeded' and result.get('schema') == 1 and type(result.get('exit_code')) is int
               and result['exit_code'] == 0 and result.get('stdout') == rid and result.get('stderr') == ''
               and result.get('truncated') is False and result.get('cursor') is None)
    return {'schema':1,'node':NODE,'request_id':rid,'status':status,'nonce_match':matched}
