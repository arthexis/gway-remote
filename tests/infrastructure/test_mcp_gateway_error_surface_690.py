"""#690: HTTP failure diagnostics have fixed, non-sensitive codes.

These are pure handler-surface tests; no sockets, credentials, remote nodes or
production services are touched.
"""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from gway_remote.mcp_bearer_gateway import Handler


class ResponseSink:
    _audit_rejection = Handler._audit_rejection
    path = '/mcp'

    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()
        self.ended = False

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        self.ended = True


class GatewayFailureDiagnosticsTests(unittest.TestCase):
    def test_upstream_failure_returns_allowlisted_code_and_correlated_private_log(self):
        sink = ResponseSink()
        journal = io.StringIO()
        with patch("gway_remote.mcp_bearer_gateway.secrets.token_hex",
                   return_value="a" * 24), contextlib.redirect_stderr(journal):
            Handler.reject(sink, 502, failure_code="upstream_unavailable")
        self.assertEqual(sink.status, 502)
        self.assertTrue(sink.ended)
        self.assertEqual(sink.headers["Content-Type"], "application/json")
        self.assertEqual(sink.headers["Cache-Control"], "no-store")
        self.assertEqual(sink.headers["X-Gway-Failure-Code"], "upstream_unavailable")
        self.assertEqual(sink.headers["X-Gway-Incident-ID"], "a" * 24)
        self.assertEqual(int(sink.headers["Content-Length"]), len(sink.wfile.getvalue()))
        payload = json.loads(sink.wfile.getvalue())
        self.assertEqual(payload, {"error": {"code": "upstream_unavailable",
                                            "incident_id": "a" * 24}})
        self.assertEqual(journal.getvalue().strip(),
                         "gway_mcp_failure code=upstream_unavailable incident_id=" + "a" * 24)

    def test_untrusted_failure_code_does_not_reflect_sensitive_text(self):
        sink = ResponseSink()
        journal = io.StringIO()
        secret = "Bearer: private-placeholder-token"
        with patch("gway_remote.mcp_bearer_gateway.secrets.token_hex",
                   return_value="b" * 24), contextlib.redirect_stderr(journal):
            Handler.reject(sink, 502, failure_code=secret)
        self.assertEqual(json.loads(sink.wfile.getvalue())["error"]["code"],
                         "gateway_internal_error")
        self.assertNotIn(secret, journal.getvalue())
        self.assertNotIn(secret, sink.wfile.getvalue().decode())

    def test_auth_challenge_and_nonserver_rejections_remain_unchanged(self):
        denied = ResponseSink()
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            Handler.reject(denied, 401, scope="gway:execute")
        entry = json.loads(journal.getvalue().removeprefix("gway_mcp_rejection "))
        self.assertEqual(entry["reason_code"], "insufficient_scope")
        self.assertEqual(entry["http_status"], 401)
        self.assertEqual(entry["route"], "mcp")
        self.assertEqual(entry["request_id"], denied.headers["X-Gway-Request-ID"])
        self.assertEqual(denied.status, 401)
        self.assertIn("insufficient_scope", denied.headers["WWW-Authenticate"])
        self.assertEqual(denied.wfile.getvalue(), b"")
        self.assertEqual(denied.headers["Content-Length"], "0")
        self.assertNotIn("X-Gway-Incident-ID", denied.headers)

        not_allowed = ResponseSink()
        Handler.reject(not_allowed, 405)
        self.assertEqual(not_allowed.status, 405)
        self.assertEqual(not_allowed.wfile.getvalue(), b"")
        self.assertEqual(not_allowed.headers["Content-Length"], "0")


if __name__ == "__main__":
    unittest.main()
