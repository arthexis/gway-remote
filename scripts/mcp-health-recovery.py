#!/usr/bin/env python3
"""One reviewed recovery recipe: restore the enabled, stopped local MCP backend.

No credentials, sudo, configuration edits, arbitrary commands or charging services.
The caller must separately establish cloud control-path failure and own the episode.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError

UNIT='gway-remote-mcp.service'
FAULT='local_remote_transport'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw): return None


def state(run=subprocess.run):
    fields=('LoadState','ActiveState','UnitFileState','InvocationID','ExecStart')
    p=run(['/usr/bin/systemctl','--user','show',UNIT,*['-p'+k for k in fields]],capture_output=True,text=True,timeout=5,check=True)
    values=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
    if set(values)!=set(fields) or 'argv[]=/usr/bin/python3 -I /opt/gway-mcp/current/run.py mcp_http ;' not in values['ExecStart']:
        raise ValueError('unexpected_backend_unit')
    return values


def pinned(revision):
    if socket.gethostname()!='gway-001' or pwd.getpwuid(os.getuid()).pw_name!='arthe' or not re.fullmatch('[0-9a-f]{40}',revision):
        return False
    root=Path('/opt/gway-mcp')
    if os.readlink(root/'current')!='releases/'+revision:
        return False
    for p in (root,root/'releases',root/'releases'/revision,root/'releases'/revision/'run.py'):
        info=p.lstat()
        if info.st_uid!=0 or info.st_mode&0o022 or stat.S_ISLNK(info.st_mode): return False
    return True


def loopback():
    request=Request('http://127.0.0.1:8770/mcp',b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',{'Content-Type':'application/json'},method='POST')
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=3):
            return 'unexpected_access'
    except HTTPError as exc:
        code=exc.code; exc.close()
        return 'protected' if code in (401,403) else 'unknown'
    except OSError as exc:
        return 'absent' if isinstance(getattr(exc,'reason',exc),ConnectionRefusedError) else 'unknown'


def eligible(revision, *, pin=pinned, inspect=state, local=loopback):
    if not pin(revision): return False
    data=inspect()
    return data['LoadState']=='loaded' and data['UnitFileState']=='enabled' and data['ActiveState'] in ('failed','inactive') and local()=='absent'


def lock(home):
    parent=home/'.local/state'; info=parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077: raise ValueError('unsafe_state')
    fd=os.open(parent/'maintenance.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1: raise ValueError('unsafe_lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd); raise


def repair(revision, *, inspect=state, local=loopback, pin=pinned, run=subprocess.run, sleep=time.sleep, acquire=lock):
    fd=acquire(Path(pwd.getpwuid(os.getuid()).pw_dir))
    try:
        if not eligible(revision,pin=pin,inspect=inspect,local=local):
            return {'outcome':'refused'}
        before=inspect()['InvocationID']
        run(['/usr/bin/systemctl','--user','start',UNIT],timeout=30,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        after=inspect()
        owned=after['InvocationID']
        if not owned or owned==before or not re.fullmatch('[0-9a-f]{32}',owned) or owned=='0'*32:
            return {'outcome':'unconfirmed'}
        for _ in range(5):
            current=inspect()
            if pin(revision) and current['InvocationID']==owned and current['ActiveState']=='active' and local()=='protected':
                return {'outcome':'applied'}
            sleep(2)
        # Restore the prior inactive posture only for our own still-active invocation.
        current=inspect()
        if current['InvocationID']==owned and current['ActiveState']=='active' and pin(revision):
            run(['/usr/bin/systemctl','--user','stop',UNIT],timeout=20,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if inspect()['ActiveState'] in ('failed','inactive') and local()=='absent':
                return {'outcome':'rolled_back'}
        return {'outcome':'unconfirmed'}
    finally:
        os.close(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('diagnose','repair'))
    parser.add_argument('--revision',required=True)
    parser.add_argument('--fault',choices=(FAULT,))
    args=parser.parse_args()
    result={'outcome':'refused'}
    try:
        if args.action=='diagnose' and args.fault is None:
            confirmed=eligible(args.revision)
            result={'fault':FAULT if confirmed else None,'local_fault_confirmed':confirmed,'independent_evidence':confirmed}
        elif args.action=='repair' and args.fault==FAULT:
            result=repair(args.revision)
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        result={'outcome':'unconfirmed'}
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
