"""Contract tests for the local MCP probe."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/mcp-local-probe.py"
spec = importlib.util.spec_from_file_location("mcp_local_probe", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LocalProbeTests(unittest.TestCase):
    def test_token_requires_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.env"
            path.write_text("GWAY_MCP_BEARER_TOKEN=local-secret\n")
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                module.read_token(path)
            path.chmod(0o600)
            self.assertEqual(module.read_token(path), "local-secret")

    def test_probe_sends_required_accept_headers(self):
        with patch.object(module, "read_token", return_value="secret"), \
             patch.object(module.urllib.request, "urlopen") as opener:
            opener.return_value.__enter__.return_value = type("Response", (), {
                "read": lambda self: b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'
            })()
            result = module.probe("tools/list", {}, credential_path=Path("/unused"))
            self.assertEqual(result["tools"], [])
            request = opener.call_args.args[0]
            self.assertIn("text/event-stream", request.get_header("Accept"))
            self.assertEqual(request.full_url, "http://127.0.0.1:8770/mcp")

    def test_no_arbitrary_tool_calls(self):
        with self.assertRaises(SystemExit) as caught:
            module.main(["--call", "node_exec", "--query", "test"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
