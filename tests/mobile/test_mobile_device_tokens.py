"""Hermetic per-device Mobile API credential tests; no Android, network ingress, or secrets."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from gway_remote.api import handler_for
from gway_remote.mobile_device_tokens import DeviceCredentials, DeviceCredentialError


class DeviceCredentialTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "private"
        self.root.mkdir(mode=0o700)
        self.db = self.root / "device.sqlite3"
        self.registry = DeviceCredentials(self.db)

    def test_issue_read_scope_hash_only_expiry_revoke(self):
        row = self.registry.issue(label="gway-001-usb-canary", now=1_800_000_000)
        self.assertEqual(self.registry.verify(row["token"], now=1_800_000_001), "read")
        self.assertIsNone(self.registry.verify(row["token"], now=row["expires_at"]))
        self.assertIsNone(self.registry.verify(row["token"] + "broken", now=1_800_000_001))
        data = self.db.read_bytes()
        self.assertNotIn(row["token"].encode(), data)
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("token", str(self.registry.list_public()))
        self.assertTrue(self.registry.revoke(row["id"]))
        self.assertFalse(self.registry.revoke(row["id"]))
        self.assertIsNone(self.registry.verify(row["token"], now=1_800_000_001))

    def test_same_active_device_does_not_receive_second_token(self):
        row = self.registry.issue(label="gway-001-usb-canary")
        with self.assertRaisesRegex(DeviceCredentialError, "active_device_credential_exists"):
            self.registry.issue(label="gway-001-usb-canary")
        self.registry.revoke(row["id"])
        self.assertNotEqual(self.registry.issue(label="gway-001-usb-canary")["id"], row["id"])

    def test_scope_validation_and_expiry(self):
        for scope in ("admin", "", None, 42):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.registry.issue(label="valid-canary", scope=scope)
        for days in (0, 91, 1.5, True):
            with self.subTest(days=days), self.assertRaises(ValueError):
                self.registry.issue(label="valid-canary", days=days)
        row = self.registry.issue(label="valid-canary", scope="execute")
        self.assertEqual(self.registry.verify(row["token"]), "execute")

    def test_insecure_database_is_unusable(self):
        row = self.registry.issue(label="device-test")
        self.db.chmod(0o644)
        self.assertIsNone(self.registry.verify(row["token"]))
        with self.assertRaises(DeviceCredentialError):
            self.registry.issue(label="another-device")
        self.db.chmod(0o600)
        self.root.chmod(0o755)
        self.assertIsNone(self.registry.verify(row["token"]))

    def test_symlink_not_accepted(self):
        row = self.registry.issue(label="device-test")
        alt = self.root / "renamed.sqlite3"
        self.db.rename(alt)
        self.db.symlink_to(alt)
        self.assertIsNone(self.registry.verify(row["token"]))
        with self.assertRaises(DeviceCredentialError):
            self.registry.issue(label="another-device")


class DeviceBearerHttpTests(DeviceCredentialTests):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler_for("legacy-secret", self.registry)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, endpoint, credential, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            headers = {"Authorization": "Bearer " + credential}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, endpoint, body=payload, headers=headers)
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read())
        finally:
            conn.close()

    def test_existing_legacy_bearer_remains_valid(self):
        self.assertEqual(self.request("GET", "/api/v1/health", "legacy-secret")[0], 200)

    def test_device_credential_allows_safe_read_and_denies_mutation(self):
        row = self.registry.issue(label="physical-samsung-canary")
        credential = row["token"]
        self.assertEqual(self.request("GET", "/api/v1/health", credential)[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/commands", credential)[0], 200)
        with patch("gway_remote.api.mobile.execute", return_value={"healthy": True}) as execute:
            payload = b'{"command":"probe-csms","arguments":{}}'
            self.assertEqual(self.request("POST", "/api/v1/execute", credential, payload)[0], 200)
            execute.assert_called_once()
            forbidden = b'{"command":"deployments-dispatch","arguments":{}}'
            self.assertEqual(self.request("POST", "/api/v1/execute", credential, forbidden)[0], 403)
            self.assertEqual(execute.call_count, 1)
        self.assertEqual(self.request("GET", "/api/v1/health", credential + "x")[0], 401)
        self.registry.revoke(row["id"])
        self.assertEqual(self.request("GET", "/api/v1/health", credential)[0], 401)

    def test_unknown_read_command_never_dispatches(self):
        row = self.registry.issue(label="physical-canary")
        with patch("gway_remote.api.mobile.execute") as execute:
            result = self.request(
                "POST", "/api/v1/execute", row["token"],
                b'{"command":"unrecognized","arguments":{}}',
            )
            self.assertEqual(result[0], 403)
            execute.assert_not_called()

    def test_unauthorized_never_dispatches(self):
        with patch("gway_remote.api.mobile.execute") as execute:
            self.assertEqual(self.request("POST", "/api/v1/execute", "missing",
                             b'{"command":"status","arguments":{}}')[0], 401)
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
