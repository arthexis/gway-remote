import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest import TestCase
from unittest.mock import patch

from gway_remote import api, mobile_feed_read as mobile
from gway_remote.activity_feed import ActivityFeedStore
from gway_remote.activity_feed_http import ActivityFeedAPI
from gway_remote.mobile_device_tokens import DeviceCredentials
from gway_remote.mcp_bearer_gateway import make_server


class DenyMcp:
    def verify(self, *args, **kwargs):
        return False


class MobileFeedTest(TestCase):
    def server(self, server):
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        return server

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        root.chmod(0o700)
        self.credentials = DeviceCredentials(root / "mobile.sqlite")
        self.device = self.credentials.issue(label="test-device", scope="read")
        self.expired = self.credentials.issue(label="expired-device", now=1)
        backend = self.server(ThreadingHTTPServer(("127.0.0.1", 0),
            api.handler_for("legacy-key", self.credentials)))
        for name, value in (("MOBILE_API_HOST", "127.0.0.1"), ("MOBILE_API_PORT", backend.server_port)):
            ctx = patch.object(mobile, name, value)
            ctx.start()
            self.addCleanup(ctx.stop)
        self.store = ActivityFeedStore(root / "feed.sqlite")
        self.store.append({"specversion":"1.0","source":"/test","id":"test","type":"test.event",
            "time":"2026-11-24T00:00:00Z","data":{"title":"Test","summary":"Synthetic",
            "category":"general","severity":"info"}}, producer="private-id", allowed_source="/test")
        self.gateway = self.server(make_server(("127.0.0.1", 0), DenyMcp(),
            "http://127.0.0.1:19011/mcp", "fake-backend",
            activity_feed=ActivityFeedAPI(self.store, DenyMcp(), lambda: {})))

    def request(self, path=mobile.MOBILE_PATH, key=None, method="GET", headers=None):
        hdr = dict(headers or {})
        if key is not None:
            hdr["Authorization"] = "Bearer " + key
        req = Request("http://127.0.0.1:" + str(self.gateway.server_port) + path,
                      method=method, headers=hdr)
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            try:
                return error.code, None
            finally:
                error.close()

    def test_legacy_and_device_key_read_only(self):
        for key in ("legacy-key", self.device["token"]):
            status, body = self.request(mobile.MOBILE_PATH+"?limit=1", key)
            self.assertEqual(status, 200)
            self.assertEqual(len(body["items"]), 1)
            self.assertNotIn("producer", body["items"][0])
            self.assertEqual(self.request(key=key, method="POST")[0], 404)
            self.assertEqual(self.request("/mcp", key, "POST")[0], 401)
            self.assertEqual(self.request("/api/feed/events", key)[0], 401)
            self.assertEqual(self.request("/api/feed/events", key, "POST")[0], 401)

    def test_invalid_revoked_expired_and_browser_keys(self):
        for key in (None, "invalid", self.expired["token"]):
            self.assertEqual(self.request(key=key)[0], 401)
        self.credentials.revoke(self.device["id"])
        self.assertEqual(self.request(key=self.device["token"])[0], 401)
        self.assertEqual(self.request(key="legacy-key", headers={"Origin":"https://test.invalid"})[0], 403)
        self.assertEqual(self.request(key="legacy-key", headers={"Content-Length":"0"})[0], 400)

    def test_disabled_and_unavailable_and_bad_query(self):
        self.assertEqual(self.request(mobile.MOBILE_PATH+"?limit=0", "legacy-key")[0], 400)
        with patch.object(mobile, "verify_mobile_key", side_effect=OSError()):
            self.assertEqual(self.request(key="legacy-key")[0], 503)
        self.gateway.activity_feed = None
        self.assertEqual(self.request(key="legacy-key")[0], 404)
        self.assertEqual(self.request(key="invalid")[0], 401)

    def test_mobile_route_is_exact_and_does_not_trust_forwarded_identity(self):
        self.assertEqual(self.request(key=None, headers={"X-Gway-Caller-Scope":"gway:read",
            "X-Forwarded-User":"operator"})[0], 401)
        self.assertEqual(self.request(mobile.MOBILE_PATH+"/1", "legacy-key")[0], 405)
        self.assertEqual(self.request(mobile.MOBILE_PATH+"?limit=1&limit=2", "legacy-key")[0], 400)

    def test_verifier_never_follows_redirect(self):
        with patch.object(mobile.http.client, "HTTPConnection") as factory:
            conn = factory.return_value
            conn.getresponse.return_value.status = 302
            with self.assertRaises(RuntimeError):
                mobile.verify_mobile_key("Bearer test-key")
            factory.assert_called_once_with("127.0.0.1", mobile.MOBILE_API_PORT, timeout=3)
            conn.request.assert_called_once()
            self.assertEqual(conn.request.call_args.args, ("GET", "/api/v1/health"))
            conn.close.assert_called_once()
