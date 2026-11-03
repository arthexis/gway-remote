"""Offline M2.1 OAuth metadata contract checks."""
import importlib.util
import pathlib
import unittest

p = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "mcp-oauth-preflight.py"
spec = importlib.util.spec_from_file_location("mcp_oauth_preflight", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ISSUER = "https://auth.gelectriic.com/application/o/gwa-remote/"
RESOURCE = {"resource": m.MCP_RESOURCE, "authorization_servers": [ISSUER]}
AUTH = {
    "issuer": ISSUER,
    "authorization_endpoint": ISSUER + "authorize/",
    "token_endpoint": ISSUER + "token/",
    "jwks_uri": ISSUER + "jwks/",
    "code_challenge_methods_supported": ["S256"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "token_endpoint_auth_methods_supported": ["client_secret_basic"],
}


class OAuthPreflightTests(unittest.TestCase):
    def test_valid_resource_and_provider(self):
        self.assertEqual(m.validate_resource(RESOURCE), ISSUER)
        self.assertTrue(m.validate_authorization(AUTH, ISSUER))

    def test_wrong_resource_rejected(self):
        with self.assertRaises(ValueError):
            m.validate_resource({**RESOURCE, "resource": "https://remote.arthexis.com/api"})

    def test_multiple_issuers_rejected(self):
        with self.assertRaises(ValueError):
            m.validate_resource({**RESOURCE, "authorization_servers": [ISSUER, "https://other.example"]})

    def test_issuer_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            m.validate_authorization({**AUTH, "issuer": ISSUER.rstrip("/")}, ISSUER)

    def test_pkce_missing_rejected(self):
        with self.assertRaises(ValueError):
            m.validate_authorization({**AUTH, "code_challenge_methods_supported": ["plain"]}, ISSUER)

    def test_client_auth_missing_rejected(self):
        with self.assertRaises(ValueError):
            m.validate_authorization({**AUTH, "token_endpoint_auth_methods_supported": []}, ISSUER)

    def test_unsafe_urls_rejected(self):
        for url in ("http://auth.gelectriic.com", "https://user:pass@auth.gelectriic.com",
                    "https://auth.gelectriic.com/#fragment", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                m.require_https(url)


if __name__ == "__main__":
    unittest.main()
