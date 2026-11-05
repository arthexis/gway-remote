"""Stage D binding: actual signed Android origin, DAL and opt-in broker gate."""
import http.client
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from gway_remote.watchtower_webauthn_admin import (
    AdminHandler, AdminCeremonies, LOOPBACK_HOST, LOOPBACK_PORT,
)
from gway_remote.watchtower_webauthn_ledger import WebAuthnLedger
from gway_remote.watchtower_webauthn_verify import (
    approved_origins, verify_assertion, verify_registration, ORIGIN,
)
from tests.infrastructure.test_watchtower_webauthn_verify import RealWebAuthnVerificationTests

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/render-passkey-assetlinks.py"
spec = importlib.util.spec_from_file_location("assetlinks_renderer", SCRIPT)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
APK_ORIGIN = renderer.render("12:" * 31 + "12")[1]


class AndroidPasskeyStageDTests(unittest.TestCase):
    def test_assetlinks_is_public_certificate_identity_not_an_auth_token(self):
        payload, origin = renderer.render("12" * 32)
        statements = json.loads(payload)
        self.assertEqual(statements[0]["target"]["package_name"], "com.arthexis.gwayremote")
        self.assertEqual(statements[0]["relation"],
                         ["delegate_permission/common.get_login_creds"])
        self.assertEqual(statements[0]["target"]["sha256_cert_fingerprints"],
                         [":".join(["12"] * 32)])
        self.assertTrue(origin.startswith("android:apk-key-hash:"))
        self.assertEqual(len(origin.split(":")[-1]), 43)
        for invalid in ("", "../a", "ff", "ZZ" * 32, "ff" * 31, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                renderer.render(invalid)

    def test_android_origin_is_not_accepted_without_pinned_config(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GWAY_WEBAUTHN_ANDROID_ORIGIN", None)
            self.assertEqual(approved_origins(), ORIGIN)
        with patch.dict(os.environ, {"GWAY_WEBAUTHN_ANDROID_ORIGIN": APK_ORIGIN}):
            self.assertEqual(approved_origins(), [ORIGIN, APK_ORIGIN])
        for value in ("https://evil.example", "android:apk-key-hash:../x",
                      "android:apk-key-hash:" + "Z" * 42, "android:apk-key-hash:"):
            with patch.dict(os.environ, {"GWAY_WEBAUTHN_ANDROID_ORIGIN": value}):
                with self.assertRaises(ValueError):
                    approved_origins()

    def test_real_registration_and_assertion_accept_only_configured_android_origin(self):
        fido = RealWebAuthnVerificationTests(
            methodName="test_real_es256_registration_and_authentication")
        fido.setUp()
        self.addCleanup(fido.tmp.cleanup)
        challenge = fido.begin("passkey.enroll", "admin")
        with self.assertRaises(Exception):
            verify_registration(fido.ledger, challenge=challenge, principal="admin",
                                credential=fido.registration(challenge, origin=APK_ORIGIN))
        challenge = fido.begin("passkey.enroll", "admin")
        with patch.dict(os.environ, {"GWAY_WEBAUTHN_ANDROID_ORIGIN": APK_ORIGIN}):
            enrolled = verify_registration(
                fido.ledger, challenge=challenge, principal="admin",
                credential=fido.registration(challenge, origin=APK_ORIGIN))
            fido.ledger._record_verified_credential(
                credential_id=enrolled.credential_id, principal="admin",
                public_key=enrolled.public_key)
            signed = fido.begin("bearer.issue", "gway-read")
            proof = verify_assertion(
                fido.ledger, challenge=signed, principal="admin",
                action="bearer.issue", target="gway-read",
                credential=fido.assertion(signed, origin=APK_ORIGIN))
            self.assertEqual(proof.credential_id, fido.cid)

    def test_capability_gate_requires_issuer_and_pinned_android_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            server = ThreadingHTTPServer((LOOPBACK_HOST, 0), AdminHandler)
            server.ceremonies = AdminCeremonies(WebAuthnLedger(Path(folder) / "test.sqlite"))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                def fetch(host=None):
                    conn = http.client.HTTPConnection(LOOPBACK_HOST, server.server_port, timeout=3)
                    conn.request("GET", "/v1/capabilities",
                                 headers={"Host": host or f"{LOOPBACK_HOST}:{LOOPBACK_PORT}"})
                    response = conn.getresponse()
                    data = json.loads(response.read())
                    status = response.status
                    conn.close()
                    return status, data

                self.assertFalse(fetch()[1]["passkeys_enabled"])
                server.issuer = object()  # Simulates privileged server injection, not token issuance.
                self.assertFalse(fetch()[1]["passkeys_enabled"])
                self.assertEqual(fetch("evil.example")[0], 403)
                with patch.dict(os.environ, {"GWAY_WEBAUTHN_ANDROID_ORIGIN": APK_ORIGIN}):
                    self.assertEqual(fetch(), (200, {
                        "passkeys_enabled": True, "rp_id": "remote.arthexis.com"}))
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)

    def test_web_proxy_remains_disabled_in_repository(self):
        root = Path(__file__).resolve().parents[2]
        snippet = root / "deploy/mcp-bearer/nginx-passkeys.conf.disabled"
        text = snippet.read_text()
        self.assertIn("127.0.0.1:19014", text)
        self.assertIn("location = /admin/v1/capabilities", text)
        self.assertIn("access_log off;", text)
        self.assertTrue(snippet.name.endswith(".disabled"))
        self.assertIn("androidx.credentials:credentials:", (
            root / "android/app/build.gradle.kts").read_text())


if __name__ == "__main__":
    unittest.main()
