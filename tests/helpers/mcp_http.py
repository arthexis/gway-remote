"""Offline HTTP/MCP request fixtures; never contact non-loopback endpoints."""
import json
from urllib.request import Request


def mcp_call(name, arguments=None, *, request_id=1):
    return json.dumps({'jsonrpc': '2.0', 'id': request_id,
                       'method': 'tools/call',
                       'params': {'name': name, 'arguments': arguments if arguments is not None else {}}}).encode()


def bearer_post(endpoint, body, token=None):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    return Request(endpoint, body, headers, method='POST')


def pkce_s256(verifier):
    """RFC 7636 S256 challenge for deterministic OAuth test verifiers."""
    import base64
    import hashlib
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
