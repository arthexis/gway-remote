"""Benchmark contract and HTTP integration tests (stdlib unittest)."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from gway_remote.api import handler_for
from gway_remote.benchmark import echo, summarize
from gway_remote.mobile import execute


class BenchmarkTests(unittest.TestCase):
    def test_echo(self):
        result = execute("benchmark-echo", {"payload": "hello"})
        self.assertEqual(result["payload"], "hello")
        self.assertEqual(result["payload_bytes"], 5)
        self.assertGreaterEqual(result["processing_ns"], 0)

    def test_invalid_echo(self):
        for args in ({}, {"payload": 4}, {"payload": "x" * 4097},
                     {"payload": "", "extra": 1}, {"payload": "é" * 2049}):
            with self.subTest(args=str(args)[:40]), self.assertRaises(ValueError):
                echo(args)

    def test_stats(self):
        self.assertEqual(summarize(list(range(1, 101)), 2),
                         {"samples": 100, "failures": 2, "median_ns": 50.5,
                          "p95_ns": 95, "min_ns": 1, "max_ns": 100})
        self.assertEqual(summarize([9])["p95_ns"], 9)
        self.assertIsNone(summarize([], 3)["median_ns"])

    def test_invalid_stats(self):
        for samples, failures in (([-1], 0), ([1.2], 0), ([True], 0),
                                  ([1], -1), ([1], True), ("bad", 0)):
            with self.subTest(samples=samples, failures=failures), self.assertRaises(ValueError):
                summarize(samples, failures)

    def test_http_authentication_and_validation(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for("test-secret"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(arguments, token="test-secret"):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                payload = json.dumps({"command": "benchmark-echo", "arguments": arguments}).encode()
                conn.request("POST", "/api/v1/execute", body=payload,
                             headers={"Authorization": "Bearer " + token,
                                      "Content-Type": "application/json"})
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        try:
            code, body = request({"payload": "ping"})
            self.assertEqual(code, 200)
            self.assertEqual(body["result"]["payload"], "ping")
            self.assertEqual(request({"payload": "ping"}, token="bad")[0], 401)
            self.assertEqual(request({"payload": 1})[0], 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
