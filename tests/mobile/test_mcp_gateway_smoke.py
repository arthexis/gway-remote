"""Deterministic contract checks for remote MCP gateway smoke validation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("mcp_smoke", Path(__file__).resolve().parents[2] / "scripts" / "mcp-smoke.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GatewaySmokeTests(unittest.TestCase):
    def test_reject_unsafe_urls(self):
        for url in ("http://remote.arthexis.com/mcp",
                    "https://user:pass@remote.arthexis.com/mcp",
                    "https://remote.arthexis.com/mcp?token=secret",
                    "https://remote.arthexis.com/api/v1/execute"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.validate_url(url)

    def test_read_only_contract(self):
        calls = []
        def transport(url, token, method, params=None):
            calls.append((token is not None, method))
            if token is None:
                return 401, b""
            if method == "initialize":
                return 200, b'{"result":{"protocolVersion":"2025-03-26"}}'
            return 200, __import__("json").dumps({"result": {"tools": [
                {"name": n, "annotations": {"readOnlyHint": True}}
                for n in sorted(module.EXPECTED)]}}).encode()
        names = module.smoke("https://remote.arthexis.com/mcp", "dummy", transport)
        self.assertEqual(set(names), module.EXPECTED)
        self.assertEqual(calls, [(False, "tools/list"), (True, "initialize"),
                                 (True, "tools/list")])

    def test_reject_missing_auth_and_mutating_tool(self):
        def unauthenticated(*args):
            return 404, b""
        with self.assertRaises(ValueError):
            module.smoke("https://remote.arthexis.com/mcp", "dummy", unauthenticated)
        def unexpected(url, token, method, params=None):
            if token is None:
                return 401, b""
            if method == "initialize":
                return 200, b'{"result":{"protocolVersion":"2025-03-26"}}'
            return 200, b'{"result":{"tools":[{"name":"agent_submit","annotations":{"readOnlyHint":false}}]}}'
        with self.assertRaises(ValueError):
            module.smoke("https://remote.arthexis.com/mcp", "dummy", unexpected)


if __name__ == "__main__":
    unittest.main()
