"""Hermetic CLI checks: never read real keys, connect SSH or mutate Watchtower."""
import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gway_remote import __main__ as cli
from gway_remote import watchtower_relay_public_key as relay


WIRE = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"K" * 32
KEY = "ssh-ed25519 " + base64.b64encode(WIRE).decode("ascii")


class WatchtowerRelayPublicKeyTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory(prefix="relay-public-key-")
        self.addCleanup(workspace.cleanup)
        self.dir = Path(workspace.name)
        self.key_path = self.dir / "existing_relay_identity"
        self.key_path.write_bytes(b"FICTIONAL PRIVATE FIXTURE -- never output")
        self.key_path.chmod(0o600)
        self.config_path = self.dir / "execute.json"
        self.nodes = [{
            "node": "gway-001",
            "address": "10.90.0.2",
            "ssh_host_alias": "gway-001",
            "known_hosts": "/var/lib/gway-mcp-exec/known_hosts",
            "identity_file": str(self.key_path),
            "host_key_sha256": "0" * 64,
            "remote_user": "gway-relay",
        }]
        self._config({"enabled": True, "nodes": self.nodes})
        self._patch(relay, "ROOT_UID", os.getuid())
        self._patch(relay.os, "geteuid", lambda: 0)
        # A fixture under /tmp is untrusted in production, so explicitly
        # isolate only its directory-ownership policy for positive tests.
        self._patch(relay, "_check_identity_parents", lambda path, owner: None)

    def _config(self, value):
        self.config_path.write_text(json.dumps(value))
        self.config_path.chmod(0o600)

    def _patch(self, target, name, value):
        p = patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def _run_ok(self, argv, **kwargs):
        self.assertEqual(argv[:5], ["/usr/bin/ssh-keygen", "-y", "-P", "", "-f"])
        self.assertEqual(len(kwargs["pass_fds"]), 1)
        self.assertEqual(argv[-1], "/proc/self/fd/" + str(kwargs["pass_fds"][0]))
        os.fstat(kwargs["pass_fds"][0])  # fd really open and trusted
        self.assertEqual(kwargs["timeout"], 5)
        self.assertFalse(kwargs["check"])
        self.assertTrue(kwargs["capture_output"])
        return SimpleNamespace(returncode=0, stdout=KEY + " fixture-comment\n", stderr="")

    def test_read_only_public_output_and_exact_stage_checksum(self):
        result = relay.export_public_key("gway-001", config=self.config_path, run=self._run_ok)
        self.assertEqual(result, {
            "node": "gway-001", "public_key": KEY,
            "sha256": hashlib.sha256((KEY + "\n").encode("ascii")).hexdigest(),
        })
        self.assertEqual(self.key_path.read_bytes(),
                         b"FICTIONAL PRIVATE FIXTURE -- never output")
        self.assertNotIn(str(self.key_path), json.dumps(result))
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_real_ssh_keygen_can_derive_via_inherited_descriptor(self):
        # Synthetic disposable key; no real Watchtower identity is read.
        import subprocess
        if not Path("/usr/bin/ssh-keygen").is_file():
            self.skipTest("OpenSSH client utility unavailable on CI host")
        self.key_path.unlink()
        subprocess.run(
            ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "",
             "-f", str(self.key_path)],
            check=True, capture_output=True, timeout=10,
        )
        report = relay.export_public_key("gway-001", config=self.config_path)
        self.assertTrue(report["public_key"].startswith("ssh-ed25519 "))
        self.assertEqual(
            report["sha256"],
            hashlib.sha256((report["public_key"] + "\n").encode("ascii")).hexdigest(),
        )

    def test_node_must_be_pinned_and_unique(self):
        with self.assertRaisesRegex(ValueError, "not configured"):
            relay.export_public_key("gway-002", config=self.config_path, run=self._run_ok)
        with self.assertRaisesRegex(ValueError, "invalid node"):
            relay.export_public_key("../../tmp", config=self.config_path, run=self._run_ok)
        self._config({"enabled": True, "nodes": self.nodes + self.nodes})
        with self.assertRaisesRegex(ValueError, "not configured uniquely"):
            relay.export_public_key("gway-001", config=self.config_path, run=self._run_ok)

    def test_config_rejects_symlink_and_untrusted_permissions(self):
        other = self.dir / "link-config"
        other.symlink_to(self.config_path)
        with self.assertRaises(OSError):
            relay.export_public_key("gway-001", config=other, run=self._run_ok)
        self.config_path.chmod(0o666)
        with self.assertRaisesRegex(ValueError, "unsafe execute configuration"):
            relay.export_public_key("gway-001", config=self.config_path, run=self._run_ok)
        self.config_path.chmod(0o600)
        self._config({"enabled": False, "nodes": self.nodes})
        with self.assertRaisesRegex(ValueError, "not enabled"):
            relay.export_public_key("gway-001", config=self.config_path, run=self._run_ok)

    def test_private_identity_is_never_followed_and_must_be_private(self):
        self.key_path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "unsafe relay identity metadata"):
            relay.export_public_key("gway-001", config=self.config_path, run=self._run_ok)
        self.key_path.chmod(0o600)
        alias = self.dir / "identity-link"
        alias.symlink_to(self.key_path)
        self.nodes[0]["identity_file"] = str(alias)
        self._config({"enabled": True, "nodes": self.nodes})
        with self.assertRaises(OSError):
            relay.export_public_key("gway-001", config=self.config_path, run=self._run_ok)

    def test_untrusted_identity_directory_is_rejected(self):
        with patch.object(relay, "_check_identity_parents", wraps=lambda p, owner:
                          (_ for _ in ()).throw(ValueError("test marker"))):
            with self.assertRaisesRegex(ValueError, "test marker"):
                relay.export_public_key("gway-001", config=self.config_path,
                                        run=self._run_ok)

    def test_derivation_and_key_format_fail_closed(self):
        def failed(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="private diagnostic")
        with self.assertRaisesRegex(ValueError, "derivation failed"):
            relay.export_public_key("gway-001", config=self.config_path, run=failed)
        def bad(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout="ssh-rsa AAAA\n", stderr="")
        with self.assertRaises(ValueError):
            relay.export_public_key("gway-001", config=self.config_path, run=bad)
        def multiple(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=KEY + "\n" + KEY, stderr="")
        with self.assertRaisesRegex(ValueError, "invalid public-key output"):
            relay.export_public_key("gway-001", config=self.config_path, run=multiple)

    def test_root_only_before_any_file_access(self):
        self._patch(relay.os, "geteuid", lambda: 1000)
        with patch.object(relay, "_config_nodes") as read:
            with self.assertRaisesRegex(ValueError, "root required"):
                relay.export_public_key("gway-001", config=self.config_path)
            read.assert_not_called()

    def test_watchtower_isolated_runtime_package_exposes_cli(self):
        """Watchtower wrapper's -I runtime must include this exact CLI action."""
        import importlib.util
        import shutil
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[2]
        stage_script = root / "scripts/stage-mcp-runtime.py"
        spec = importlib.util.spec_from_file_location("mcp_runtime_stage", stage_script)
        stage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stage)

        source = stage_script.read_text(encoding="utf-8")
        self.assertIn('"gway_remote", "deploy/mcp-bearer"', source)
        self.assertIn('runpy.run_module("gway_remote.__main__"', stage.LAUNCHER)

        wrapper = (root / "deploy/mcp-bearer/gway-remote-watchtower-cli").read_text()
        self.assertIn('/usr/bin/python3 -I /opt/gway-mcp/current/run.py cli "$@"',
                      wrapper)

        with TemporaryDirectory(prefix="watchtower-runtime-") as isolated:
            runtime = Path(isolated)
            shutil.copytree(root / "gway_remote", runtime / "gway_remote")
            launcher = runtime / "run.py"
            launcher.write_text(stage.LAUNCHER, encoding="utf-8")
            process = subprocess.run(
                [sys.executable, "-I", str(launcher), "cli",
                 "watchtower", "--help"],
                capture_output=True, text=True, timeout=15, check=False,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("relay-public-key", process.stdout)

    def test_watchtower_cli_is_local_only_and_does_not_load_ledger(self):
        report = {"node": "gway-001", "public_key": KEY, "sha256": "a" * 64}
        with patch("sys.argv", ["gway-remote", "watchtower",
                                "relay-public-key", "gway-001"]), \
             patch.object(relay, "export_public_key", return_value=report) as exporter, \
             patch("gway_remote.watchtower_enrollment.Ledger") as ledger, \
             patch("builtins.print") as output:
            cli.main()
        exporter.assert_called_once_with("gway-001")
        ledger.assert_not_called()
        self.assertEqual(json.loads(output.call_args.args[0]), report)


if __name__ == "__main__":
    unittest.main()
