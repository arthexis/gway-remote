"""HTTP adapter tests: no live services or chargers are touched."""
import unittest
from unittest.mock import patch

from gway_remote.api import serve
from tests.support.http_api import LocalApiCase
from gway_remote import mobile


class MobileTests(unittest.TestCase):
    def test_codex_read_only_catalog_entries(self):
        names = {entry["name"] for entry in mobile.commands()}
        self.assertIn("codex-tasks", names)
        self.assertIn("codex-task", names)

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

    def test_github_health_is_read_only_and_authenticated(self):
        with patch("gway_remote.api.github_health.read_snapshot",
                   return_value={"status": "available", "repositories": [], "alerts": []}) as reader:
            status, body = self.request("GET", "/api/v1/github-health")
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "available")
            reader.assert_called_once_with()
        with patch("gway_remote.api.github_health.read_snapshot") as reader:
            self.assertEqual(self.request("GET", "/api/v1/github-health", token="bad")[0], 401)
            self.assertEqual(self.request("POST", "/api/v1/github-health", b'{}')[0], 404)
            reader.assert_not_called()

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

    def test_agent_issue_acknowledgement_is_not_execution_completion(self):
        payload = b'{"command":"agent-issue","arguments":{"ref":"owner/repo#2","at":"2026-10-13T15:00:00Z"}}'
        for state, expected in (("requested", "requested"),
                                ("already_requested", "already_requested"),
                                ("launch_unconfirmed", "unknown")):
            with self.subTest(state=state):
                with patch.object(mobile, "execute", return_value={
                    "schema_version": 1, "command": "submit", "status": "ok",
                    "data": {"state": state}, "error": None}):
                    status, response = self.request("POST", "/api/v1/execute", payload)
                self.assertEqual(status, 200)
                self.assertEqual(response["status"], expected)
                self.assertNotEqual(response["status"], "completed")

    def test_rejects_unsafe_and_invalid_requests(self):
        for payload in (b'{"command":"run","arguments":{}}',
                        b'{"command":"status","arguments":{"now":true}}'):
            self.assertEqual(self.request("POST", "/api/v1/execute", payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'broken')[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'[]')[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'{}',
                                      headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/v1/execute", b'x' * 8193)[0], 413)

    def test_unauthorized_request_never_dispatches(self):
        with patch.object(mobile, "execute") as execute:
            for method, path, payload in (
                ("GET", "/api/v1/commands", None),
                ("POST", "/api/v1/execute", b'{"command":"status","arguments":{}}'),
            ):
                with self.subTest(method=method, path=path):
                    status, body = self.request(method, path, payload, token="wrong")
                    self.assertEqual(status, 401)
                    self.assertEqual(body["error"], "unauthorized")
            execute.assert_not_called()

    def test_invalid_requests_never_dispatch(self):
        invalid = (
            (b'{"command":"run","arguments":{}}', 400),
            (b'{"command":"status","arguments":{"now":true}}', 400),
            (b'{"command":"status"}', 400),
            (b'[]', 400),
            (b'broken', 400),
            (b'x' * 8193, 413),
        )
        with patch.object(mobile, "execute", side_effect=ValueError("invalid")) as execute:
            for payload, expected in invalid:
                with self.subTest(payload=payload[:40]):
                    status, _ = self.request("POST", "/api/v1/execute", payload)
                    self.assertEqual(status, expected)
            # Valid JSON commands reach dispatch, which independently enforces admission.
            self.assertEqual(execute.call_count, 2)

    def test_response_never_contains_sensitive_exception_details(self):
        with patch.object(mobile, "execute", side_effect=RuntimeError("token=private-secret")):
            status, body = self.request("POST", "/api/v1/execute",
                                        b'{"command":"status","arguments":{}}')
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "execution_failed"})
        self.assertNotIn("private-secret", str(body))

    def test_unknown_routes_do_not_dispatch(self):
        with patch.object(mobile, "execute") as execute:
            for method, path in (("GET", "/api/v1/unknown"), ("POST", "/api/v1/unknown")):
                with self.subTest(method=method):
                    status, body = self.request(method, path, b'{}' if method == "POST" else None)
                    self.assertEqual(status, 404)
                    self.assertEqual(body["error"], "not_found")
            execute.assert_not_called()

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
