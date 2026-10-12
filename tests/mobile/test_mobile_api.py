"""HTTP adapter tests: no live services or chargers are touched."""
import unittest
from unittest.mock import patch

from gway_remote.api import serve
from tests.support.http_api import LocalApiCase
from gway_remote import mobile


class MobileTests(unittest.TestCase):
    def test_rejects_mutations_and_arguments(self):
        for name in ("run", "deploy-batch", "logs", "reconcile", "report-bundle"):
            with self.assertRaises(ValueError):
                mobile.execute(name, {})
        with self.assertRaises(ValueError):
            mobile.execute("status", {"unexpected": 1})

    def test_rejects_other_bind_addresses(self):
        for host in ("0.0.0.0", "192.168.1.10", "10.90.0.1", "::"):
            with self.subTest(host=host), self.assertRaisesRegex(ValueError, "WireGuard"):
                serve(host, 0, "test")

    def test_loopback_and_wireguard_bind_are_accepted(self):
        with patch("gway_remote.api.ThreadingHTTPServer", side_effect=RuntimeError("created")) as server:
            for host in ("127.0.0.1", "10.90.0.2"):
                with self.subTest(host=host), self.assertRaisesRegex(RuntimeError, "created"):
                    serve(host, 8765, "test")
                self.assertEqual(server.call_args.args[0], (host, 8765))


class ApiTests(LocalApiCase):
    def test_health_and_catalog(self):
        self.assertEqual(self.request("GET", "/api/v1/health")[0], 200)
        status, body = self.request("GET", "/api/v1/commands")
        self.assertEqual(status, 200)
        self.assertIn("status", {c["name"] for c in body["commands"]})
        self.assertIn("probe-csms", {c["name"] for c in body["commands"]})

    def test_authentication(self):
        self.assertEqual(self.request("GET", "/api/v1/commands", token="bad")[0], 401)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'{}', token="bad")[0], 401)

    def test_execution_uses_existing_operation(self):
        with patch.dict(mobile.OPERATIONS, {"probe-csms": lambda: {"healthy": True}}):
            status, body = self.request("POST", "/api/v1/execute",
                                        b'{"command":"probe-csms","arguments":{}}')
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["healthy"])
        self.assertIsInstance(body["execution_ns"], int)
        self.assertGreaterEqual(body["execution_ns"], 0)

    def test_rejects_unsafe_and_invalid_requests(self):
        for payload in (b'{"command":"run","arguments":{}}',
                        b'{"command":"status","arguments":{"now":true}}'):
            self.assertEqual(self.request("POST", "/api/v1/execute", payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'broken')[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'[]')[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'{}',
                                      headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'x' * 8193)[0], 413)

    def test_operation_failure_does_not_leak_details(self):
        def fail():
            raise RuntimeError("private secret")

        with patch.dict(mobile.OPERATIONS, {"status": fail}):
            status, body = self.request("POST", "/api/v1/execute",
                                        b'{"command":"status","arguments":{}}')
        self.assertEqual(status, 500)
        self.assertNotIn("private secret", str(body))


if __name__ == "__main__":
    unittest.main()
