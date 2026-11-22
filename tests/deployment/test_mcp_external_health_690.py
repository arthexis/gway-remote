"""The external probe reports only fixed classes, never secrets or node data."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

path = Path(__file__).resolve().parents[2] / 'scripts/mcp-external-health.py'
spec = importlib.util.spec_from_file_location('mcp_external_health_690', path)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class Response(io.BytesIO):
    status = 200


class ExternalHealthTests(unittest.TestCase):
    def test_private_credential_file_and_symlink_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            credential = folder / 'token'
            credential.write_text('private-token\n')
            credential.chmod(0o600)
            self.assertEqual(health.read_token(credential), 'private-token')
            credential.chmod(0o644)
            with self.assertRaises(ValueError):
                health.read_token(credential)
            credential.chmod(0o600)
            link = folder / 'link'
            link.symlink_to(credential)
            with self.assertRaises(OSError):
                health.read_token(link)
            folder.chmod(0o777)
            with self.assertRaises(ValueError):
                health.read_token(credential)

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
