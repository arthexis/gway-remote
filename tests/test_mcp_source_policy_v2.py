"""Regression tests for generic MCP source policy v2 (#449)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.mcp_source_policy import load_source_policy


def registration(source_id="reports", enabled=True):
    return {
        "source_id": source_id,
        "revision": "a" * 40,
        "executable": "/opt/mcp/bin/server",
        "argv": ["/opt/mcp/bin/server"],
        "run_as": "mcpsvc",
        "enabled": enabled,
        "permission": "read",
    }


class RegistrationOnlyPolicyTests(unittest.TestCase):
    def load(self, policy, *, wrong_digest=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            raw = json.dumps(policy).encode()
            path.write_bytes(raw)
            digest = ("0" * 64 if wrong_digest else hashlib.sha256(raw).hexdigest())
            real_stat = path.stat()
            class RootOwned:
                st_uid = 0
                st_mode = real_stat.st_mode
            # Only redirect the protected file lookup; keep all other validation.
            with patch("gway_remote.mcp_source_policy.Path", return_value=path), patch.object(
                Path, "stat", return_value=RootOwned()
            ):
                return load_source_policy(
                    "/etc/gway-mcp-gateway/sources.json", expected_sha256=digest
                )

    def test_v2_two_sources_need_no_tool_catalog(self):
        policy = {"version": 2, "sources": [
            {"registration": registration("reports")},
            {"registration": registration("inventory")},
        ]}
        registrations, catalogs = self.load(policy)
        self.assertEqual([r.source_id for r in registrations], ["reports", "inventory"])
        self.assertEqual(catalogs, {"reports": [], "inventory": []})

    def test_v1_compatibility(self):
        policy = {"version": 1, "sources": [
            {"registration": registration(), "tools": []},
        ]}
        registrations, catalogs = self.load(policy)
        self.assertEqual(registrations[0].source_id, "reports")
        self.assertEqual(catalogs, {"reports": []})

    def test_v2_rejects_static_tool_catalog(self):
        policy = {"version": 2, "sources": [
            {"registration": registration(), "tools": []},
        ]}
        with self.assertRaises(ValueError):
            self.load(policy)

    def test_v1_still_requires_catalog_field(self):
        with self.assertRaises(ValueError):
            self.load({"version": 1, "sources": [{"registration": registration()}]})

    def test_disabled_source_not_advertised(self):
        registrations, catalogs = self.load({"version": 2, "sources": [
            {"registration": registration(enabled=False)},
        ]})
        self.assertFalse(registrations[0].enabled)
        self.assertEqual(catalogs, {})

    def test_duplicate_source_rejected(self):
        with self.assertRaises(ValueError):
            self.load({"version": 2, "sources": [
                {"registration": registration()},
                {"registration": registration()},
            ]})

    def test_digest_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):
            self.load({"version": 2, "sources": []}, wrong_digest=True)

    def test_write_permission_rejected(self):
        item = registration()
        item["permission"] = "execute"
        with self.assertRaises(ValueError):
            self.load({"version": 2, "sources": [{"registration": item}]})


if __name__ == "__main__":
    unittest.main()
