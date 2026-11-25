"""Restricted MCP ingress for an exclusive-purpose probe credential.

No fallthrough to normal MCP tools. Activation is separately provisioned and
must require the ordinary authenticated private bridge when it is configured.
"""
import json
import secrets
import time
from .mcp_health_probe_contract import NODE,SCOPE,validate_call
from .mcp_bridge_gateway_session import gateway_bridge_session
from .mcp_bridge_transport import call_unix
from .mcp_health_probe_execution import ProbeExecution

NAMES={'node_exec':'health_probe.start','node_result':'health_probe.result','node_exec_diagnostic':'health_probe.diagnostic'}


def dispatch(server, token, name, arguments):
    rid=validate_call(name,arguments)
    if name not in NAMES:
        raise PermissionError('probe_operation_not_enabled')
    principal=server.registry.health_probe_principal(token)
    if server.execution is None:
        raise PermissionError('probe_execution_unavailable')
    if server.bridge_transport is None:
        adapter=ProbeExecution(server.execution)
        value={'node_exec':adapter.start,'node_result':adapter.result,'node_exec_diagnostic':adapter.diagnostic}[name](principal,arguments)
    else:
        if server.bridge_sessions is None:
            raise PermissionError('probe_bridge_unavailable')
        now=int(time.time());path,key=server.bridge_transport
        envelope={'version':1,'request_id':secrets.token_hex(16),'principal':principal,'audience':NODE,'operation':NAMES[name],'scope':SCOPE,'issued_at':now,'expires_at':now+30,'arguments':arguments}
        with gateway_bridge_session(server.bridge_sessions,bearer=token,audience=NODE) as sid:
            value=call_unix(path,key,envelope,session_id=sid,timeout=20,require_signed_reply=True)
    if name=='node_exec_diagnostic':
        if (type(value) is not dict or value.get('request_id')!=rid or not (
                set(value)=={'request_id','status'} and value['status']=='unknown' or
                set(value)=={'request_id','status','stage'} and value['status']=='failure' and value['stage'] in ('ssh_transport','worker_readiness'))):
            raise PermissionError('invalid_probe_diagnostic')
        return value
    if (type(value) is not dict or set(value)!={'schema','node','request_id','status','nonce_match'} or value['schema']!=1 or value['node']!=NODE or value['request_id']!=rid or type(value['nonce_match']) is not bool or value['status'] not in ('dispatched','uncertain','queued','running','succeeded','failed','cancelled','timed_out','unknown') or (value['nonce_match'] and value['status']!='succeeded')):
        raise PermissionError('invalid_probe_projection')
    return value


def rpc(server, token, payload):
    if type(payload) is not dict or payload.get('jsonrpc')!='2.0' or set(payload)-{'jsonrpc','id','method','params'}:
        raise ValueError('invalid_probe_rpc')
    method=payload.get('method');params=payload.get('params',{})
    if type(params) is not dict: raise ValueError('invalid_probe_params')
    if method=='notifications/initialized' and 'id' not in payload and not params:
        return None
    if type(payload.get('id')) not in (int,str):raise ValueError('invalid_probe_id')
    if method=='initialize' and set(params)=={'protocolVersion','capabilities','clientInfo'} and params['protocolVersion']=='2025-03-26':
        result={'protocolVersion':'2025-03-26','capabilities':{'tools':{}},'serverInfo':{'name':'gway-health-probe','version':'1'}}
    elif method=='tools/list' and not params:
        nonce={'type':'string','pattern':'^[0-9a-f]{32}$'}
        tools=[]
        for name in NAMES:
            props={'request_id':nonce}
            if name=='node_exec': props.update(node={'const':NODE,'type':'string'},command={'type':'string','pattern':'^printf %s [0-9a-f]{32}$'},wait_seconds={'const':0,'type':'integer'})
            tools.append({'name':name,'description':'Restricted health nonce probe','inputSchema':{'type':'object','properties':props,'required':list(props),'additionalProperties':False}})
        result={'tools':tools}
    elif method=='tools/call' and set(params)=={'name','arguments'}:
        value=dispatch(server,token,params['name'],params['arguments'])
        result={'content':[{'type':'text','text':json.dumps(value,separators=(',',':'))}]}
    else:raise PermissionError('probe_rpc_denied')
    return {'jsonrpc':'2.0','id':payload['id'],'result':result}
