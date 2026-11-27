"""Hermetic native framing, declaration, and Firefox permission checks."""
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import unittest
from unittest.mock import patch

from gway_remote import browser_contract as contract, browser_mcp
from gway_remote.mcp_tool_scope import required_scope
from gway_remote.mcp_source_policy import classify_source_catalog
from gway_remote.mcp_source_registry import SourceRegistration

ROOT = Path(__file__).resolve().parents[2]

class BrowserContractTests(unittest.TestCase):
    def test_framing_and_bounds(self):
        value = {"operation": "snapshot"}
        stream = io.BytesIO(contract.encode(value))
        self.assertEqual(contract.receive(stream.read), value)
        for data in (b"", struct.pack("=I", 0), struct.pack("=I", contract.MAX + 1),
                     struct.pack("=I", 12) + b"{}"):
            with self.assertRaises((ValueError, EOFError)):
                contract.receive(io.BytesIO(data).read)
        with self.assertRaises(ValueError):
            contract.encode({"large": "x" * contract.MAX})

    def test_only_fixed_requests(self):
        for req in (
            {"operation": "click", "ref": "1" * 32, "url": "https://example.invalid"},
            {"operation": "click", "ref": "bad"}, {"operation": "evaluate"},
            {"operation": "snapshot", "script": "arbitrary"}, {"operation": "fill"},
            {"operation": "scenario_run", "scenario": "other"},
            {"operation": "status", "node": "other"},
        ):
            with self.subTest(req=req), self.assertRaises(ValueError):
                contract.validate_request(req)
        self.assertEqual(contract.validate_request({"operation": "click", "ref": "a" * 32})["ref"], "a" * 32)

    def test_projection_rejects_raw_sensitive_or_unbounded_data(self):
        base = {"ok": True, "state": "ready", "page": "rfid",
                "controls": [{"ref": "a" * 32, "kind": "rfid_next"}],
                "evidence": {"history_page": 1, "history_chart": True}}
        self.assertEqual(contract.validate_result(base), base)
        for bad in (
            {**base, "html": "raw"}, {**base, "url": "https://example.invalid"},
            {**base, "evidence": {"password": "secret"}},
            {**base, "evidence": {"history_page": "raw text"}},
            {**base, "controls": [{"ref": "a"*32, "kind": "rfid_next", "label": "raw"}]},
            {**base, "controls": base["controls"]*33},
        ):
            with self.assertRaises(ValueError):
                contract.validate_result(bad)

    def test_existing_federation_classification(self):
        r = SourceRegistration("browser", "a"*40, "/opt/browser/mcp",
                               ("/opt/browser/mcp",), "arthe", True)
        catalog = classify_source_catalog(r, contract.declarations())
        self.assertEqual([t["name"] for t in catalog["read"]], ["snapshot", "status"])
        self.assertEqual([t["name"] for t in catalog["execute_required"]], ["click", "scenario_run"])
        self.assertEqual(required_scope(catalog["execute_required"][0]), "execute")

    def test_unavailable_without_consent_and_no_extra_arguments(self):
        with patch.object(browser_mcp, "call", side_effect=FileNotFoundError):
            result = browser_mcp.dispatch("tools/call", {"name": "status", "arguments": {}})
        self.assertTrue(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"])["state"], "unavailable")
        with self.assertRaises(ValueError):
            browser_mcp.dispatch("tools/call", {"name": "status", "arguments": {"operation": "click"}})

    def test_minimal_extension_permissions_and_no_persistent_profile_access(self):
        manifest = json.loads((ROOT / "browser/firefox/manifest.json").read_text())
        self.assertEqual(set(manifest["permissions"]), {"activeTab", "nativeMessaging"})
        self.assertNotIn("content_scripts", manifest)
        self.assertNotIn("host_permissions", manifest)
        self.assertNotIn("optional_permissions", manifest)
        self.assertNotIn("externally_connectable", manifest)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_extension_syntax_and_mocked_consent(self):
        for name in ("background.js", "reports.js"):
            subprocess.run(["node", "--check", str(ROOT / "browser/firefox" / name)], check=True, timeout=10)
        subprocess.run(["node", str(ROOT / "browser/tests/consent.test.js")], check=True, timeout=10)
