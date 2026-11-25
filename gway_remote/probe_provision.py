"""Trusted Watchtower console; first-time isolated probe delivery, no secrets printed."""
import argparse
import fcntl
import json
import os
import pwd
import re
import sys
import time
import uuid
from .activity_feed_provision import _child, AUTH, GATEWAY, DATABASE
from .mcp_bearer import BearerRegistry, PROBE_SCOPE, _lookup

NODE='gway-001'
ID=re.compile('[0-9a-f]{24}')


def internal(action,payload):
    account=AUTH if action in ('issue','verify','revoke') else GATEWAY
    if os.geteuid()!=pwd.getpwnam(account).pw_uid:raise PermissionError('wrong service identity')
    if action=='issue':
        if set(payload)!={'days'} or type(payload['days']) is not int or not 1<=payload['days']<=30:raise ValueError('invalid lifetime')
        if not DATABASE.is_file() or DATABASE.is_symlink():raise PermissionError('issuer unavailable')
        return BearerRegistry(DATABASE).issue_health_probe_pair(lifetime=payload['days']*86400,operator_approved=True)
    if action in ('verify','revoke'):
        if set(payload)!={'parent_id'} or not ID.fullmatch(payload['parent_id']):raise ValueError('invalid parent')
        parent=payload['parent_id'];row=_lookup(DATABASE,parent)
        if not row or row[1]!=PROBE_SCOPE:raise PermissionError('wrong credential purpose')
        if action=='revoke':BearerRegistry(DATABASE).revoke(parent);return {'revoked':True}
        return {'valid':row[3] is None and row[2]>int(time.time()),'parent_expires_at':row[2]}
    if action=='status' and not payload:op='probe_provision_status'
    elif action=='install' and set(payload)=={'credential'}:op='probe_provision_install'
    else:raise ValueError('invalid delivery request')
    from .watchtower_exec_service import load_service
    from .watchtower_exec_transport import pinned_transport
    service=load_service();service._current_eligibility(NODE)
    transport=pinned_transport(service.relay.transport,NODE)
    if transport.node.remote_user not in ('arthe','gway-relay'):raise PermissionError('approved installation transport required')
    rid=uuid.uuid4().hex
    result=transport.invoke({'operation':op,'node':NODE,'request_id':rid,**payload})
    if result.get('node')!=NODE or result.get('request_id')!=rid or type(result.get('result')) is not dict:raise PermissionError('uncorrelated delivery')
    return result['result']


class ProvisionStageError(RuntimeError):
    def __init__(self,stage):
        self.stage=stage
        super().__init__('private provisioning stage failed')


def child(account,action,payload):
    try:return _child(account,action,payload,handler=internal)
    except Exception:raise ProvisionStageError(action if action in ('status','issue','install','verify','revoke') else 'unknown') from None


def check_receipt(receipt,*,invoke):
    if set(receipt)!={'configured','parent_id','parent_expires_at','refresh_state'} or receipt['configured'] is not True or not ID.fullmatch(receipt['parent_id']) or receipt['refresh_state']!='ready':raise PermissionError('unverified existing credential')
    verified=invoke(AUTH,'verify',{'parent_id':receipt['parent_id']})
    if verified!={'valid':True,'parent_expires_at':receipt['parent_expires_at']}:raise PermissionError('credential parent unavailable')
    return {'node':NODE,'scope':PROBE_SCOPE,'configured':True,'parent_id':receipt['parent_id'],'parent_expires_at':receipt['parent_expires_at'],'delivery':'verified','live_probe':'pending','recovery_enabled_by_command':False}


def provision(days,*,invoke=child):
    old=invoke(GATEWAY,'status',{})
    if old!={'configured':False}:return check_receipt(old,invoke=invoke)
    state=invoke(AUTH,'issue',{'days':days});parent=state['parent_id']
    if not ID.fullmatch(parent):raise RuntimeError('invalid issuer receipt')
    try:
        try:receipt=invoke(GATEWAY,'install',{'credential':state})
        except Exception:receipt=invoke(GATEWAY,'status',{})
        if receipt.get('parent_id')!=parent or receipt.get('parent_expires_at')!=state['parent_expires_at']:raise PermissionError('delivery identity mismatch')
        return check_receipt(receipt,invoke=invoke)
    except BaseException:
        invoke(AUTH,'revoke',{'parent_id':parent});raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('node',choices=[NODE]);parser.add_argument('--days',type=int,default=30);args=parser.parse_args(argv)
    try:
        if os.geteuid()!=0 or not sys.stdin.isatty() or not sys.stdout.isatty():raise PermissionError('interactive root console required')
        if not 1<=args.days<=30:raise ValueError('invalid lifetime')
        if input('Type gway-001 to provision the isolated health probe: ').strip()!=NODE:raise PermissionError('operator confirmation required')
        fd=os.open('/var/lib/gway-mcp-auth/probe-provision.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            print(json.dumps(provision(args.days),sort_keys=True))
        finally:os.close(fd)
        return 0
    except ProvisionStageError as exc:
        print('Probe provisioning failed at stage: '+exc.stage+'. Reconcile before replacement. No recovery activation.',file=sys.stderr);return 1
    except (Exception,KeyboardInterrupt):
        print('Probe provisioning refused or uncertain; reconcile before replacement. No recovery activation.',file=sys.stderr);return 1
