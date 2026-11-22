#!/usr/bin/env python3
"""Authenticated external read-only MCP probe. No credentials in argv or output."""
import json
import os
from pathlib import Path
import stat
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

URL = 'https://remote.arthexis.com/mcp'
TOKEN_FILE = Path('/etc/gway-mcp-monitor/oauth-access-token')


def read_token(path=TOKEN_FILE):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= 4096):
            raise ValueError('unsafe credential')
        token = stream.read(4097).decode('ascii').strip()
    if not token or len(token) > 4096 or any(c.isspace() or ord(c) < 33 for c in token):
        raise ValueError('invalid credential')
    return token


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
        return 'ok'
    except HTTPError as exc:
        code = exc.code
        exc.close()
        return 'authentication_failed' if code in (401, 403) else 'transport_failed'
    except (OSError, URLError, ValueError, TypeError):
        return 'transport_failed'


def main():
    try:
        result = probe(read_token())
    except (OSError, ValueError, UnicodeError):
        result = 'credential_unavailable'
    print(json.dumps({'status': result}))
    return 0 if result == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
