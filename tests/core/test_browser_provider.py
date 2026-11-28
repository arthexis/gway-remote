"""Hermetic native framing, declaration, and Firefox permission checks."""
import io
import json
import os
import selectors
import socket
import sys
import tempfile
import time
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

    def test_bounded_dispatch_states(self):
        for state in ("tab_recheck_failed", "permission_recheck_failed", "script_injection_failed",
                      "adapter_message_failed", "adapter_response_invalid", "adapter_execution_failed",
                      "response_post_failed"):
            result = {"ok": False, "state": state}
            self.assertEqual(contract.validate_result(result), result)
            with self.assertRaises(ValueError):
                contract.validate_result({**result, "error": "private exception"})
        with self.assertRaises(ValueError):
            contract.validate_result({"ok": False, "state": "arbitrary error message"})

    def test_existing_federation_classification(self):
        r = SourceRegistration("browser", "a"*40, "/opt/browser/mcp",
                               ("/opt/browser/mcp",), "arthe", True)
        catalog = classify_source_catalog(r, contract.declarations())
        self.assertEqual([t["name"] for t in catalog["read"]], ["snapshot", "status"])
        self.assertEqual([t["name"] for t in catalog["execute_required"]], ["click", "scenario_run"])
        self.assertEqual(required_scope(catalog["execute_required"][0]), "execute")

    def test_unavailable_without_consent_and_no_extra_arguments(self):
        for error, state in ((FileNotFoundError, "lease_absent"),
                             (PermissionError, "bridge_access_denied"),
                             (TimeoutError, "bridge_timeout"),
                             (ConnectionRefusedError, "bridge_unreachable"),
                             (ValueError, "bridge_protocol_error"),
                             (EOFError, "bridge_protocol_error")):
            with self.subTest(state=state), patch.object(browser_mcp, "call", side_effect=error("private detail")):
                result = browser_mcp.dispatch("tools/call", {"name": "status", "arguments": {}})
                self.assertTrue(result["isError"])
                self.assertEqual(json.loads(result["content"][0]["text"]), {"ok": False, "state": state})
        with self.assertRaises(ValueError):
            browser_mcp.dispatch("tools/call", {"name": "status", "arguments": {"operation": "click"}})

    def test_minimal_extension_permissions_and_no_persistent_profile_access(self):
        manifest = json.loads((ROOT / "browser/firefox/manifest.json").read_text())
        self.assertEqual(set(manifest["permissions"]), {"activeTab", "nativeMessaging"})
        self.assertNotIn("content_scripts", manifest)
        self.assertNotIn("host_permissions", manifest)
        self.assertEqual(manifest["optional_permissions"], ["https://reports.example.invalid/*"])
        self.assertNotIn("externally_connectable", manifest)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_extension_syntax_and_mocked_consent(self):
        for name in ("background.js", "reports.js"):
            subprocess.run(["node", "--check", str(ROOT / "browser/firefox" / name)], check=True, timeout=10)
        subprocess.run(["node", str(ROOT / "browser/tests/consent.test.js")], check=True, timeout=10)

    @unittest.skipIf(os.geteuid() == 0, "Native host must run as non-root")
    def test_native_stdio_roundtrip_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private" / "bridge.sock"
            # Test-only overrides: use a synthetic HTTPS origin, fixture socket
            # and canary hostname; real native host never accepts overrides.
            script = (
                "from pathlib import Path; from unittest.mock import patch; "
                "from gway_remote import browser_native as n; import sys; "
                "p=Path(sys.argv[1]); "
                "a=patch.object(n,'policy',return_value='https://reports.example.test'); "
                "b=patch.object(n,'socket_path',return_value=p); "
                "c=patch.object(n.socket,'gethostname',return_value='gway-001'); "
                "a.start(); b.start(); c.start(); sys.exit(n.main())"
            )
            proc = subprocess.Popen([sys.executable, "-c", script, str(path)],
                                    cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            def read(size):
                with selectors.DefaultSelector() as sel:
                    sel.register(proc.stdout, selectors.EVENT_READ)
                    self.assertTrue(sel.select(3), "native message deadline")
                return os.read(proc.stdout.fileno(), size)
            try:
                self.assertEqual(contract.receive(read)["origin"], "https://reports.example.test")
                self.assertFalse(path.exists())
                proc.stdin.write(contract.encode({"consent": True}))
                proc.stdin.flush()
                self.assertEqual(contract.receive(read), {"bridge_ready": True})
                self.assertTrue(path.is_socket())
                end = time.monotonic() + 3
                while not path.exists() and time.monotonic() < end:
                    time.sleep(.02)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(3)
                    client.connect(str(path))
                    client.sendall(contract.encode({"operation": "snapshot"}))
                    self.assertEqual(contract.receive(read), {"operation": "snapshot"})
                    evidence = {"ok": True, "state": "ready", "page": "dashboard",
                                "evidence": {"rfid_summary_rows": 4}}
                    proc.stdin.write(contract.encode(evidence))
                    proc.stdin.flush()
                    self.assertEqual(contract.receive(client.recv), evidence)
                proc.stdin.close()
                self.assertEqual(proc.wait(timeout=3), 0)
                self.assertFalse(path.exists())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=3)
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    stream.close()
