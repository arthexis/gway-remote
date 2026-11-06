"""Offline checks for the operator-only MCP source field preflight."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gway_remote.mcp_source_registry import SourceRegistration


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/mcp-source-preflight.py"
spec = importlib.util.spec_from_file_location("mcp_source_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def test_rejects_mutable_and_unapproved_executable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "current" / "bin" / "source"
            path.parent.mkdir(parents=True)
            path.write_text("#!/bin/sh\n")
            path.chmod(0o755)
            user = preflight.pwd.getpwuid(preflight.os.geteuid()).pw_name
            reg = SourceRegistration("pilot", "a" * 40, str(path), (str(path),), user, True)
            with self.assertRaisesRegex(ValueError, "pinned release"):
                preflight.verify_source(reg, [])

    def test_catalog_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "releases" / ("a" * 40) / "bin" / "source"
            path.parent.mkdir(parents=True)
            path.write_text("#!/bin/sh\n")
            path.chmod(0o755)
            user = preflight.pwd.getpwuid(preflight.os.geteuid()).pw_name
            reg = SourceRegistration("pilot", "a" * 40, str(path), (str(path),), user, True)
            with patch.object(preflight.os, "geteuid", return_value=1000), \
                 patch.object(preflight.pwd, "getpwuid", return_value=type("U", (), {"pw_name": user})()), \
                 patch.object(preflight, "list_source_tools", return_value=[{"name": "unexpected"}]):
                with self.assertRaisesRegex(ValueError, "catalog differs"):
                    preflight.verify_source(reg, [{"name": "approved"}])


if __name__ == "__main__":
    unittest.main()
