"""In-process, loopback-only HTTP API test fixture."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from gway_remote.api import handler_for


class LocalApiCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for("test-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, payload=None, token="test-secret", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        self.addCleanup(conn.close)
        hdrs = {"Authorization": "Bearer " + token}
        if payload is not None:
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=payload, headers=hdrs)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
