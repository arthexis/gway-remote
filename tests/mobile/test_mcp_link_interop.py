"""OAuth optional parameters and secret-free failure diagnostics, hermetic HTTP."""
import base64
import hashlib
import http.client
import json
import io
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_link import LinkFlow, RESOURCE
from gway_remote import mcp_link_http

CLIENT = 'private-client'
CALLBACK = 'https://chatgpt.com/connector_platform_oauth_redirect'


class OAuthInteropTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.registry = BearerRegistry(Path(home.name) / 'registry.sqlite')
        self.flow = LinkFlow(self.registry, client_id=CLIENT, redirect_uri=CALLBACK)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), mcp_link_http.Handler)
        self.server.link = self.flow
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.verifier = 'v' * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b'=').decode()
        self.params = dict(client_id=CLIENT, redirect_uri=CALLBACK, resource=RESOURCE,
                           response_type='code', code_challenge=challenge,
                           code_challenge_method='S256', state='private-state', scope='gway:read')

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=data, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def authorize(self, params):
        return self.request('GET', '/oauth/authorize?' + urlencode(params))

    def exchange(self, changes=None):
        session, _ = self.flow.begin(**self.params)
        dest = self.flow.connect(session, self.flow.pending[session][0], self.registry.issue())
        code = parse_qs(urlsplit(dest).query)['code'][0]
        values = dict(client_id=CLIENT, redirect_uri=CALLBACK, resource=RESOURCE,
                      grant_type='authorization_code', code=code, code_verifier=self.verifier)
        values.update(changes or {})
        return self.request('POST', '/oauth/token', urlencode(values),
                            {'Content-Type': 'application/x-www-form-urlencoded'})

    def test_authorization_ignores_extension_and_empty_parameters(self):
        for extra in ({'prompt': 'consent', 'login_hint': 'opaque-private@example.invalid'},
                      {'client_secret': '', 'extension': ''}):
            with self.subTest(extra=tuple(extra)):
                status, headers, body = self.authorize({**self.params, **extra})
                self.assertEqual(status, 200)
                self.assertIn('Set-Cookie', headers)
                self.assertIn(b'type=\'password\'', body)

    def test_omitted_or_empty_scope_defaults_only_to_registered_read_scope(self):
        for scope in (None, ''):
            params = {k: v for k, v in self.params.items() if k != 'scope'}
            if scope is not None:
                params['scope'] = scope
            with self.subTest(scope=scope):
                self.assertEqual(self.authorize(params)[0], 200)
        status, headers, _ = self.authorize({**self.params, 'scope': 'gway:submit', 'prompt': 'consent'})
        self.assertEqual(status, 303)
        self.assertEqual(parse_qs(urlsplit(headers['Location']).query)['error'], ['invalid_scope'])

    def test_token_ignores_extensions_and_blank_client_secret(self):
        status, _, body = self.exchange({'client_secret': '', 'extension': 'opaque-private'})
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload['scope'], 'gway:read')
        self.assertTrue(BearerVerifier(self.registry.path).verify(payload['access_token']))

    def test_nonempty_secret_is_not_silently_treated_as_authenticated(self):
        status, _, body = self.exchange({'client_secret': 'unstored-secret'})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {'error': 'invalid_client'})

    def test_real_http_diagnostics_never_contain_request_or_credentials(self):
        output = io.StringIO()
        proof = self.registry.issue()
        state = 'sensitive-state-sentinel'
        with patch('sys.stderr', output), patch.object(mcp_link_http, 'AUDIT', mcp_link_http.OAuthAudit()), patch.dict('os.environ', {'GWAY_MCP_OAUTH_DIAGNOSTICS': '1'}):
            status, headers, _ = self.authorize({**self.params, 'state': state, 'login_hint': 'private-hint-sentinel'})
            self.assertEqual(status, 200)
            cookie = headers['Set-Cookie'].split(';', 1)[0]
            session = cookie.split('=', 1)[1]
            csrf = self.flow.pending[session][0]
            status, headers, _ = self.request('POST', '/connect', urlencode({'csrf': csrf, 'bearer': proof}),
                                             {'Content-Type': 'application/x-www-form-urlencoded', 'Cookie': cookie})
            self.assertEqual(status, 303)
            code = parse_qs(urlsplit(headers['Location']).query)['code'][0]
            form = dict(client_id=CLIENT, redirect_uri=CALLBACK, resource=RESOURCE,
                        grant_type='authorization_code', code=code, code_verifier=self.verifier, client_secret='')
            status, _, body = self.request('POST', '/oauth/token', urlencode(form),
                                            {'Content-Type': 'application/x-www-form-urlencoded'})
            self.assertEqual(status, 200)
            access = json.loads(body)['access_token']
            self.assertEqual(self.authorize({**self.params, 'client_id': 'private-attacker-sentinel'})[0], 400)
        logs = output.getvalue()
        for private in (proof, state, session, csrf, code, access, self.verifier,
                        'private-hint-sentinel', 'private-attacker-sentinel', CLIENT, CALLBACK, RESOURCE):
            self.assertNotIn(private, logs)
        records = [json.loads(line) for line in logs.splitlines()]
        self.assertEqual([(r['phase'], r['reason'], r['status']) for r in records],
                         [('authorize', 'page', 200), ('connect', 'code', 303),
                          ('token', 'issued', 200), ('authorize', 'invalid_client', 400)])
        self.assertFalse(records[-1]['client_match'])
        self.assertTrue(records[-1]['redirect_match'])

    def test_optional_parameters_do_not_bypass_client_binding_or_duplicates(self):
        for change in ({'client_id': 'other'}, {'redirect_uri': 'https://evil.invalid/cb'},
                       {'resource': 'https://evil.invalid/mcp'}, {'code_challenge_method': 'plain'}):
            with self.subTest(change=tuple(change)):
                self.assertNotEqual(self.authorize({**self.params, **change, 'prompt': 'consent'})[0], 200)
        self.assertEqual(self.authorize([*self.params.items(), ('scope', 'gway:submit')])[0], 400)
        status, _, _ = self.request('POST', '/oauth/token', 'code=a&code=b',
                                   {'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(status, 400)


class OAuthAuditTests(unittest.TestCase):
    def test_diagnostics_schema_rejects_request_text_and_limits_volume(self):
        output = io.StringIO()
        audit = mcp_link_http.OAuthAudit()
        with patch.dict('os.environ', {'GWAY_MCP_OAUTH_DIAGNOSTICS': '1'}), patch('sys.stderr', output), patch('gway_remote.mcp_link_http.time.monotonic', return_value=100):
            audit.emit('caller-controlled-phase', 'caller-controlled-reason', 400)
            for _ in range(200):
                audit.emit('authorize', 'invalid_client', 400,
                           {'client_match': False, 'redirect_match': True, 'scope_read': 'private-value',
                            'private-parameter-name': 'private-token'})
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(records), 61)
        self.assertEqual(records[-1]['reason'], 'rate_limited')
        self.assertFalse(records[0]['client_match'])
        self.assertTrue(records[0]['redirect_match'])
        self.assertNotIn('scope_read', records[0])
        self.assertNotIn('private', output.getvalue())
        self.assertTrue(all(len(line) < 512 for line in output.getvalue().splitlines()))

    def test_diagnostics_can_be_disabled(self):
        output = io.StringIO()
        with patch.dict('os.environ', {'GWAY_MCP_OAUTH_DIAGNOSTICS': '0'}), patch('sys.stderr', output):
            mcp_link_http.OAuthAudit().emit('token', 'issued', 200)
        self.assertEqual(output.getvalue(), '')
