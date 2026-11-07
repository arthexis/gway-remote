"""Regression tests for dynamic v2 registration validation."""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.mcp_source_policy import load_source_policy


REGISTRATION = {
    "source_id": "odoo", "revision": "a" * 40,
    "executable": "/opt/odoo/bin/odoo-mcp",
    "argv": ["/opt/odoo/bin/odoo-mcp"], "run_as": "arthe",
    "enabled": True,
}


class SourcePolicyV2Tests(unittest.TestCase):
    def load(self, policy):
        raw = json.dumps(policy).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_bytes(raw)
            with patch("gway_remote.mcp_source_policy.Path", return_value=path):
                with patch.object(Path, "stat", autospec=True) as stat:
                    # The production loader requires a root-owned file.
                    actual = path.stat()
                    stat.return_value = type("Stat", (), {"st_uid": 0, "st_mode": actual.st_mode})()
                    return load_source_policy(
                        "/etc/gway-mcp-gateway/sources.json",
                        expected_sha256=hashlib.sha256(raw).hexdigest())

    def test_v2_enabled_source_requires_no_static_tools(self):
        registrations, approved = self.load({
            "version": 2, "sources": [{"registration": REGISTRATION}]})
        self.assertEqual(len(registrations), 1)
        self.assertEqual(approved, {"odoo": []})

    def test_v2_rejects_duplicate_source(self):
        with self.assertRaises(ValueError):
            self.load({"version": 2, "sources": [
                {"registration": REGISTRATION}, {"registration": REGISTRATION}]})

    def test_v2_rejects_static_tool_list(self):
        with self.assertRaises(ValueError):
            self.load({"version": 2, "sources": [
                {"registration": REGISTRATION, "tools": []}]})


if __name__ == "__main__":
    unittest.main()
