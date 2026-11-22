"""The external probe reports only fixed classes, never secrets or node data."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

path = Path(__file__).resolve().parents[2] / 'scripts/mcp-external-health.py'
spec = importlib.util.spec_from_file_location('mcp_external_health_690', path)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class Response(io.BytesIO):
    status = 200


class ExternalHealthTests(unittest.TestCase):
    def state(self, expires=9999):
        return {'client_id': 'observer-client', 'access_token': 'access-private',
                'refresh_token': 'refresh-private', 'expires_at': expires,
                'refresh_state': 'ready', 'parent_expires_at': 9999999}

    def test_private_credential_file_and_symlink_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            credential = folder / 'token'
            credential.write_text(json.dumps(self.state()))
            credential.chmod(0o600)
            self.assertEqual(health.access_token(credential, now=lambda: 1000), 'access-private')
            credential.chmod(0o644)
            with self.assertRaises(ValueError):
                health.access_token(credential)
            credential.chmod(0o600)
            link = folder / 'link'
            link.symlink_to(credential)
            with self.assertRaises(OSError):
                health.access_token(link)
            folder.chmod(0o777)
            with self.assertRaises(ValueError):
                health.access_token(credential)

    def test_rotation_persists_new_pair_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential = Path(tmp) / 'oauth.json'
            credential.write_text(json.dumps(self.state(expires=1000)))
            credential.chmod(0o600)
            payload = {'scope': 'gway:read', 'token_type': 'Bearer', 'expires_in': 3600,
                       'access_token': 'new-access', 'refresh_token': 'new-refresh'}
            token = health.access_token(credential, now=lambda: 1000,
                opener=lambda *a, **kw: Response(json.dumps(payload).encode()))
            self.assertEqual(token, 'new-access')
            stored = json.loads(credential.read_text())
            self.assertEqual(stored['refresh_token'], 'new-refresh')
            self.assertEqual(stored['refresh_state'], 'ready')
            self.assertEqual(credential.stat().st_mode & 0o777, 0o600)

    def test_uncertain_refresh_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential = Path(tmp) / 'oauth.json'
            credential.write_text(json.dumps(self.state(expires=1000)))
            credential.chmod(0o600)
            calls = []
            def unavailable(*args, **kwargs):
                calls.append(1)
                raise TimeoutError('private exception')
            for _ in range(2):
                with self.assertRaises(health.RefreshUncertain):
                    health.access_token(credential, now=lambda: 1000, opener=unavailable)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(credential.read_text())['refresh_state'], 'uncertain')

    def test_refresh_with_broader_scope_is_rejected_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential = Path(tmp) / 'oauth.json'
            credential.write_text(json.dumps(self.state(expires=1000)))
            credential.chmod(0o600)
            payload = {'scope': 'gway:execute', 'token_type': 'Bearer', 'expires_in': 3600,
                       'access_token': 'bad-access', 'refresh_token': 'bad-refresh'}
            with self.assertRaises(health.RefreshUncertain):
                health.access_token(credential, now=lambda: 1000,
                    opener=lambda *a, **kw: Response(json.dumps(payload).encode()))
            self.assertEqual(json.loads(credential.read_text())['refresh_state'], 'uncertain')

    def test_expiring_parent_never_reports_healthy(self):
        with patch.object(health, 'access_token', return_value='private'), \
             patch.object(health, 'probe', return_value='ok'), \
             patch.object(health, '_read_state', return_value={'parent_expires_at': 1001}), \
             patch.object(health.time, 'time', return_value=1000), \
             patch('builtins.print') as report:
            self.assertEqual(health.main(), 1)
            self.assertEqual(json.loads(report.call_args.args[0])['status'], 'credential_expiring')

    def test_authenticated_node_list(self):
        seen = []
        def open_request(request, timeout):
            seen.append((request.get_method(), json.loads(request.data), timeout))
            response = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [
                {'type': 'text', 'text': json.dumps({'schema': 1, 'nodes': []})}]}}
            return Response(json.dumps(response).encode())
        self.assertEqual(health.probe('private-token', opener=open_request), 'ok')
        self.assertEqual(seen[0][1]['params']['name'], 'node_list')
        self.assertNotIn('private-token', repr(seen))

    def test_http_auth_and_tool_errors_are_distinct(self):
        def denied(*args, **kwargs):
            raise HTTPError('private-url', 401, 'private', {}, None)
        self.assertEqual(health.probe('private-token', opener=denied), 'authentication_failed')
        self.assertEqual(health.probe('private-token', opener=lambda *a, **kw:
            Response(b'{"id":1,"result":{"isError":true}}')), 'tool_failed')
