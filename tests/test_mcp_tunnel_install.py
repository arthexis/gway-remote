"""Installer and runtime contract tests for opt-in MCP tunnel; no network access."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TunnelInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "systemctl.log"
        self._executable("tunnel-client", "#!/bin/sh\nexit 0\n")
        self._executable("systemctl", '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"\n')
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=str(self.bin) + ":" + os.environ["PATH"],
                        SYSTEMCTL_LOG=str(self.log))

    def _executable(self, name, contents):
        p = self.bin / name
        p.write_text(contents)
        p.chmod(0o755)

    def install(self):
        return subprocess.run(["sh", str(ROOT / "scripts/install-mcp-tunnel.sh")],
                              env=self.env, text=True, capture_output=True)

    def test_fails_closed_without_local_mcp_credentials(self):
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / ".config/gway-remote/tunnel.env").exists())

    def test_installs_without_activation_or_overwriting_credentials(self):
        mcp = self.home / ".config/gway-remote/mcp.env"
        mcp.parent.mkdir(parents=True)
        mcp.write_text("GWAY_MCP_BEARER_TOKEN=sample-secret\n")
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        config = self.home / ".config/gway-remote/tunnel.env"
        config.write_text("CONTROL_PLANE_TUNNEL_ID=tunnel_demo\n")
        second = self.install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(config.read_text(), "CONTROL_PLANE_TUNNEL_ID=tunnel_demo\n")
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(mcp.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(mcp.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.home / ".local/bin/gway-run-mcp-tunnel").stat().st_mode), 0o700)
        self.assertEqual(self.log.read_text().strip().splitlines(),
                         ["--user daemon-reload", "--user daemon-reload"])

    def test_wrapper_passes_token_only_to_local_mcp_header(self):
        result_path = self.root / "runtime.json"
        self._executable("tunnel-client",
                         '#!/usr/bin/env python3\n'
                         'import json, os\n'
                         'with open(os.environ["CAPTURE_PATH"], "w") as f:\n'
                         ' json.dump({"url": os.environ.get("MCP_SERVER_URL"),'
                         '"header": os.environ.get("MCP_EXTRA_HEADERS"),'
                         '"discovery": os.environ.get("MCP_DISCOVERY_EXTRA_HEADERS"),'
                         '"key": os.environ.get("CONTROL_PLANE_API_KEY")}, f)\n')
        env = dict(self.env, CONTROL_PLANE_API_KEY="test-runtime-key",
                   CONTROL_PLANE_TUNNEL_ID="tunnel_demo",
                   GWAY_MCP_BEARER_TOKEN="local-mcp-secret",
                   CAPTURE_PATH=str(result_path))
        proc = subprocess.run(["sh", str(ROOT / "scripts/run-mcp-tunnel.sh")],
                              env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(result_path.read_text())
        self.assertEqual(data["url"], "http://127.0.0.1:8770/mcp")
        self.assertEqual(data["header"], "Authorization: Bearer local-mcp-secret")
        self.assertEqual(data["discovery"], data["header"])
        self.assertEqual(data["key"], "test-runtime-key")

    def test_wrapper_requires_distinct_credentials(self):
        env = dict(self.env, CONTROL_PLANE_TUNNEL_ID="tunnel_demo",
                   GWAY_MCP_BEARER_TOKEN="local-secret")
        result = subprocess.run(["sh", str(ROOT / "scripts/run-mcp-tunnel.sh")],
                                env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
