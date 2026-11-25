#!/usr/bin/env python3
"""Authenticated external read-only MCP probe. No credentials in argv or output."""
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

URL = 'https://remote.arthexis.com/mcp'
TOKEN_FILE = Path('/etc/gway-mcp-monitor/oauth.json')
REFRESH_URL = 'https://remote.arthexis.com/oauth/token'


class RefreshUncertain(Exception):
    """A one-use refresh may have been consumed; never replay it."""


def _private_parent(path):
    parent = path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or parent.st_mode & 0o022):
        raise ValueError('unsafe credential directory')


def _read_state(path):
    _private_parent(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= 16384):
            raise ValueError('unsafe credential')
        state = json.loads(stream.read(16385))
    required = {'client_id', 'access_token', 'refresh_token', 'expires_at', 'refresh_state'}
    if (type(state) is not dict or set(state) != required | {'parent_expires_at'}
            or any(type(state.get(k)) is not str or not state[k]
                   or len(state[k]) > 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in state[k])
                   for k in ('client_id', 'access_token', 'refresh_token'))
            or type(state.get('expires_at')) is not int
            or type(state.get('parent_expires_at')) is not int
            or state.get('refresh_state') not in ('ready', 'uncertain')):
        raise ValueError('invalid credential')
    return state


def _write_state(path, state):
    _private_parent(path)
    fd, name = tempfile.mkstemp(prefix='.oauth-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def access_token(path=TOKEN_FILE, *, opener=urlopen, now=time.time):
    """Refresh with a durable, fail-closed marker before a one-use request.

    A crash or uncertain response requires explicit re-provisioning, never replay.
    """
    _private_parent(path)
    lockfd = os.open(path.parent / '.oauth.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lockfd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('unsafe lock')
        fcntl.flock(lockfd, fcntl.LOCK_EX)
        state = _read_state(path)
        if state['refresh_state'] != 'ready':
            raise RefreshUncertain()
        if state['expires_at'] > int(now()) + 120:
            return state['access_token']
        state['refresh_state'] = 'uncertain'
        _write_state(path, state)
        body = urlencode({'grant_type': 'refresh_token', 'client_id': state['client_id'],
                          'refresh_token': state['refresh_token'], 'resource': URL}).encode()
        request = Request(REFRESH_URL, data=body, method='POST', headers={
            'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        try:
            with opener(request, timeout=15) as response:
                raw = response.read(16385)
                if response.status != 200 or len(raw) > 16384:
                    raise ValueError('refresh failed')
            result = json.loads(raw)
            if (type(result) is not dict or result.get('scope') != 'gway:read'
                    or type(result.get('token_type')) is not str
                    or result['token_type'].lower() != 'bearer'
                    or type(result.get('expires_in')) is not int
                    or not 1 <= result['expires_in'] <= 3600
                    or any(type(result.get(k)) is not str or not result[k]
                           or len(result[k]) > 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in result[k])
                           for k in ('access_token', 'refresh_token'))):
                raise ValueError('invalid refresh response')
            state.update(access_token=result['access_token'], refresh_token=result['refresh_token'],
                         expires_at=int(now()) + result['expires_in'], refresh_state='ready')
            _write_state(path, state)
            return state['access_token']
        except (OSError, ValueError, TypeError, URLError):
            raise RefreshUncertain() from None
    finally:
        os.close(lockfd)


def probe(token, *, opener=urlopen):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': 'node_list', 'arguments': {}}}).encode()
    request = Request(URL, data=body, method='POST', headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-03-26'})
    try:
        with opener(request, timeout=20) as response:
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                return 'transport_failed'
        result = json.loads(raw)
        if (not isinstance(result, dict) or result.get('id') != 1
                or not isinstance(result.get('result'), dict)
                or result['result'].get('isError') is True):
            return 'tool_failed'
        content = result['result'].get('content')
        if (not isinstance(content, list) or len(content) != 1
                or not isinstance(content[0], dict) or content[0].get('type') != 'text'
                or not isinstance(content[0].get('text'), str)):
            return 'tool_failed'
        inventory = json.loads(content[0]['text'])
        if (not isinstance(inventory, dict) or inventory.get('schema') != 1
                or not isinstance(inventory.get('nodes'), list)):
            return 'tool_failed'
        monitor = inventory.get('watchtower_monitor')
        if type(monitor) is not dict or set(monitor) != {'status'} or monitor['status'] not in ('ok', 'failed', 'unknown'):
            return 'watchtower_monitor_unavailable'
        if monitor['status'] != 'ok':
            return 'watchtower_monitor_failed' if monitor['status'] == 'failed' else 'watchtower_monitor_unavailable'
        return 'ok'
    except HTTPError as exc:
        code = exc.code
        exc.close()
        return 'authentication_failed' if code in (401, 403) else 'transport_failed'
    except (OSError, URLError, ValueError, TypeError):
        return 'transport_failed'


PROJECTION = Path('/var/lib/gway-mcp-external-health/status.json')
EXTENDED_INTERVAL = 900

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def decode_tool_result(result):
    """Gateway builtins wrap once; federated stdio providers wrap twice."""
    def unwrap(envelope):
        if not isinstance(envelope,dict) or envelope.get('isError') is True:
            raise ValueError('tool_failed')
        content=envelope.get('content')
        if not isinstance(content,list) or len(content)!=1 or not isinstance(content[0],dict) or content[0].get('type')!='text' or not isinstance(content[0].get('text'),str):
            raise ValueError('invalid_tool_envelope')
        return json.loads(content[0]['text'])
    payload=unwrap(result)
    if isinstance(payload,dict) and 'content' in payload:
        payload=unwrap(payload)
    if not isinstance(payload,(dict,list)) or isinstance(payload,dict) and ('content' in payload or 'error' in payload or payload.get('isError') is True):
        raise ValueError('invalid_tool_payload')
    return payload


def extended_probe(token, *, opener=None):
    """Fixed read-only calls; no response content or credentials in projection."""
    opener = opener or build_opener(NoRedirect()).open
    deadline=time.monotonic()+105
    def rpc(method, params, auth=True):
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-03-26'}
        if auth:
            headers['Authorization']='Bearer '+token
        req=Request(URL,json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers,method='POST')
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise TimeoutError('probe_budget')
        with opener(req,timeout=min(20,remaining)) as response:
            raw=response.read(1048577)
            if response.status!=200 or len(raw)>1048576:
                raise ValueError('response_limit')
        doc=json.loads(raw)
        if doc.get('id')!=1 or 'error' in doc or not isinstance(doc.get('result'),dict):
            raise ValueError('protocol_failure')
        return doc['result']
    def call(name,args):
        result=rpc('tools/call',{'name':name,'arguments':args})
        return decode_tool_result(result)
    report={'anonymous':'unavailable','read':'unavailable','optional_failures':0,'optional_checked':0}
    try:
        rpc('tools/list',{},False)
        report['anonymous']='unexpected_access'
    except HTTPError as exc:
        report['anonymous']='denied' if exc.code in (401,403) else 'unavailable'
        exc.close()
    except (OSError,ValueError,TypeError,AttributeError):
        pass
    try:
        init=rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'gway-health','version':'1'}})
        if init.get('protocolVersion')!='2025-03-26':
            raise ValueError('protocol_failure')
        tools=rpc('tools/list',{})['tools']
        schemas={r['name']:r['inputSchema'] for r in tools}
        rows=call('mcp_catalog_inspect',{})['tools']
        def route(name,node):
            return {'node':node} if 'node' in schemas[name].get('properties',{}) else {}
        def declared(name,node):
            return name in schemas and any(r.get('name')==name and r.get('required_scope')=='gway:read' and node in (r.get('nodes') or [r.get('node')]) for r in rows)
        name='agentops__daily_health_status'
        if not declared(name,'gway-001') or call(name,route(name,'gway-001')).get('schedule',{}).get('id')!='gway-001-daily-health':
            raise ValueError('provider_failure')
        preview=call('node_exec_preview',{'node':'gway-001','command':'true'})
        if preview.get('node')!='gway-001' or preview.get('status')!='preview_only' or preview.get('authorization',{}).get('required_scope')!='gway:execute':
            raise ValueError('preview_contract_failed')
        report['read']='ok'
        for name,node in [('agentops__status','gway-001'),('agentops__status','gway-004'),('gway_004_agentops__status','gway-004'),('android__status','gway-001'),('ocpp__charger_list','gway-001'),('odoo__currency_list','gway-001')]:
            if declared(name,node) and (node=='gway-001' or route(name,node) or name.startswith('gway_004_')):
                report['optional_checked']+=1
                try:
                    args=route(name,node)
                    if name=='odoo__currency_list':
                        args['limit']=1
                    payload=call(name,args)
                    if not isinstance(payload,(dict,list)) or isinstance(payload,dict) and ('error' in payload or payload.get('status')=='error'):
                        raise ValueError('optional_provider_failed')
                except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError):
                    report['optional_failures']+=1
    except HTTPError as exc:
        report['read']='authorization' if exc.code in (401,403) else 'http_failure'
        exc.close()
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError):
        report['read']='transport_or_protocol'
    return report


def read_projection(path):
    try:
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o022 or info.st_size>4096:
            return None
        return json.loads(path.read_text())
    except (OSError,ValueError,TypeError):
        return None


def publish_extended(token, *, base_status="ok", path=PROJECTION, now=time.time, probe=extended_probe):
    parent=path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.geteuid() or parent.st_mode&0o022:
        raise ValueError('unsafe_projection_directory')
    previous=read_projection(path)
    stamp=int(now())
    if (base_status=='ok' and isinstance(previous,dict) and previous.get('schema')==1 and previous.get('read')=='ok' and previous.get('anonymous')=='denied'
            and type(previous.get('sample_at')) is int and 0<=stamp-previous['sample_at']<EXTENDED_INTERVAL):
        return
    if token and base_status not in ('credential_expiring','authentication_failed'):
        report=probe(token)
    else:
        report={'anonymous':'unavailable','read':'authorization','optional_checked':0,'optional_failures':0}
    data={'schema':1,'sample_at':stamp,**report}
    fd,name=tempfile.mkstemp(prefix='.status-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            os.fchmod(f.fileno(),0o644)
            json.dump(data,f,sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(extended=False):
    token=None
    try:
        token=access_token()
        result = probe(token)
        if result == 'ok' and _read_state(TOKEN_FILE)['parent_expires_at'] <= int(time.time()) + 7 * 86400:
            result = 'credential_expiring'
    except RefreshUncertain:
        result = 'refresh_uncertain'
    except (OSError, ValueError, UnicodeError):
        result = 'credential_unavailable'
    if extended:
        try:
            publish_extended(token,base_status=result)
        except (OSError,ValueError,TypeError):
            # A stale extended projection will be rejected by its consumer.
            pass
    print(json.dumps({'status': result}))
    return 0 if result == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main(extended=sys.argv[1:]==["--extended"]))
