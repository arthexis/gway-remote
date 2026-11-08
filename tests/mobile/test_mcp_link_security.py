from tests.helpers.mcp_http import pkce_s256
"""OAuth grant revocation, bounded state and ambiguous HTTP rejection."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from http.server import ThreadingHTTPServer

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_link import LinkFlow
from gway_remote.mcp_link_http import Handler as LinkHandler
from gway_remote.mcp_bearer_gateway import make_server
from gway_remote.mcp_http import Handler as BackendHandler


class LinkSecurityTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.registry = BearerRegistry(Path(self.home.name) / 'tokens.db')
        self.bearer = self.registry.issue()
        self.flow = LinkFlow(self.registry, client_id='private-client', redirect_uri='https://chatgpt.com/approved-callback')
        self.verifier = 'x' * 43
        self.params = dict(client_id=self.flow.client_id, redirect_uri=self.flow.redirect_uri,
                           resource=self.flow.resource, response_type='code',
                           code_challenge=pkce_s256(self.verifier),
                           code_challenge_method='S256', state='valid-state', scope='gway:read')

    def code(self):
        session, _ = self.flow.begin(**self.params)
        dest = self.flow.connect(session, self.flow.pending[session][0], self.bearer)
        return parse_qs(urlsplit(dest).query)['code'][0]

    def redeem(self, code):
        return self.flow.redeem(client_id=self.flow.client_id, redirect_uri=self.flow.redirect_uri,
                                resource=self.flow.resource, grant_type='authorization_code',
                                code=code, code_verifier=self.verifier)

    def test_revoked_proof_cannot_redeem_and_existing_children_are_revoked(self):
        old_code = self.code()
        child = self.redeem(self.code())['access_token']
        verifier = BearerVerifier(self.registry.path)
        self.assertTrue(verifier.verify(child))
        self.registry.revoke(self.bearer.split('_')[1])
        with self.assertRaises(ValueError):
            self.redeem(old_code)
        # Fresh verifier represents a restarted gateway, without cached state.
        self.assertFalse(BearerVerifier(self.registry.path).verify(child))

    def test_child_expiry_cannot_exceed_parent_and_parent_chain_revokes(self):
        with patch('gway_remote.mcp_bearer.time.time', return_value=1000):
            parent = self.registry.issue(lifetime=60)
            child = self.registry.issue(parent_id=parent.split('_')[1])
            grandchild = self.registry.issue(parent_id=child.split('_')[1])
            self.assertTrue(self.registry.verify(grandchild))
        with patch('gway_remote.mcp_bearer.time.time', return_value=1060):
            self.assertFalse(self.registry.verify(child))
            self.assertFalse(self.registry.verify(grandchild))

    def test_capacity_rejects_then_reclaims_expired_state(self):
        with patch('gway_remote.mcp_link.MAX_PENDING', 2), patch('gway_remote.mcp_link.time.monotonic', return_value=1000):
            self.code()
            self.flow.begin(**self.params)
            with self.assertRaises(ValueError):
                self.flow.begin(**self.params)
        with patch('gway_remote.mcp_link.MAX_PENDING', 2), patch('gway_remote.mcp_link.time.monotonic', return_value=1400):
            self.flow.begin(**self.params)
            self.assertEqual(len(self.flow.pending), 1)
            self.assertEqual(len(self.flow.codes), 0)

    def request(self, server, path, headers, body):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            self.addCleanup(client.close)
            client.putrequest('POST', path)
            for key, value in headers:
                client.putheader(key, value)
            client.endheaders(body)
            response = client.getresponse()
            response.read()
            return response.status
        finally:
            server.shutdown()
            thread.join()

    def test_gateway_and_backend_reject_ambiguous_headers_without_upstream(self):
        body = json.dumps({'jsonrpc':'2.0', 'id':1, 'method':'tools/list'}).encode()
        base = [('Authorization', 'Bearer ' + self.bearer), ('Content-Type', 'application/json'),
                ('Content-Length', str(len(body))), ('Accept', 'application/json, text/event-stream')]
        for extra, expected in [([('Authorization', 'Bearer other')], 401),
                                ([('Content-Length', str(len(body)))], 400),
                                ([('Content-Type', 'application/json')], 400),
                                ([('Transfer-Encoding', 'chunked')], 400)]:
            with self.subTest(extra=extra), patch.dict(os.environ, GWAY_MCP_BEARER_TOKEN=self.bearer):
                with ThreadingHTTPServer(('127.0.0.1', 0), BackendHandler) as server:
                    self.assertEqual(self.request(server, '/mcp', base + extra, body), expected)
                with make_server(('127.0.0.1', 0), BearerVerifier(self.registry.path), 'http://127.0.0.1:1/mcp', 'backend') as server:
                    self.assertEqual(self.request(server, '/mcp', base + extra, body), expected)

    def test_link_rejects_duplicate_fields_and_transfer_encoding(self):
        body = b'csrf=first&csrf=second&bearer=invalid'
        base = [('Content-Type', 'application/x-www-form-urlencoded'), ('Content-Length', str(len(body)))]
        for extra in ([], [('Transfer-Encoding', 'chunked')], [('Content-Length', str(len(body)))]):
            with self.subTest(extra=extra), ThreadingHTTPServer(('127.0.0.1', 0), LinkHandler) as server:
                server.link = self.flow
                self.assertEqual(self.request(server, '/connect', base + extra, body), 400)
