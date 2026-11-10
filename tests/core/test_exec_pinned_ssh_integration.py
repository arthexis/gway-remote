"""Offline SSH pinned transport and forced-command contract integration."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from gway_remote.watchtower_exec_transport import PinnedNode, SSHTransport

RID = "a" * 32


class PinnedTransportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        key = bytes(range(32))
        self.digest = hashlib.sha256(key).hexdigest()
        self.known = self.root / "known_hosts"
        self.identity = self.root / "executor_key"
        self.known.write_text("gway-001 ssh-ed25519 " + base64.b64encode(key).decode() + "\n")
        self.identity.write_text("test-only placeholder; never a real key\n")
        self.known.chmod(0o600)
        self.identity.chmod(0o600)

    def node(self, **changes):
        values = dict(node="gway-001", wireguard_address="10.42.0.2",
                      ssh_host_alias="gway-001", known_hosts=self.known,
                      identity_file=self.identity, host_key_sha256=self.digest,
                      installer_user="installer")
        values.update(changes)
        return PinnedNode(**values)

    def test_ssh_argv_uses_pinned_identity_and_protocol_marker(self):
        calls = []
        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(stdout=json.dumps({
                "node": "gway-001", "request_id": RID,
                "concurrent_jobs_per_node": 1}).encode())
        response = SSHTransport(self.node(), run=fake_run).invoke({
            "operation": "limits", "node": "gway-001", "request_id": RID})
        self.assertEqual(response["concurrent_jobs_per_node"], 1)
        argv, kwargs = calls[0]
        self.assertEqual(argv[-1], "gway-exec-protocol-v1")
        self.assertEqual(argv[argv.index("-l") + 1], "installer")
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("ClearAllForwardings=yes", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("-T", argv)
        self.assertNotIn("/bin/sh", argv)
        self.assertEqual(json.loads(kwargs["input"])["operation"], "limits")

    def test_transport_to_forced_command_to_protocol_offline(self):
        """Exercise the actual request bytes through the fixed entrypoint, no SSH or jobs."""
        import runpy
        from unittest.mock import patch
        from gway_remote import node_exec_protocol

        entrypoint = Path(__file__).resolve().parents[2] / "scripts/node-exec-forced-command.py"
        calls = []

        class ProtocolReached(Exception):
            pass

        def fake_execve(executable, argv, env):
            self.assertEqual(argv, ["/usr/bin/python3", "-m", "gway_remote.node_exec_protocol"])
            self.assertEqual(env["USER"], "installer")
            self.assertNotIn("SSH_AUTH_SOCK", env)
            raise ProtocolReached

        def fake_ssh(argv, **kwargs):
            self.assertEqual(argv[-1], "gway-exec-protocol-v1")
            self.assertIn("-T", argv)
            self.assertIn("ClearAllForwardings=yes", argv)
            calls.append(argv)
            with patch.dict(os.environ, {
                "SSH_ORIGINAL_COMMAND": argv[-1],
                "SSH_CONNECTION": "192.0.2.1 12345 192.0.2.2 22",
                "SSH_AUTH_SOCK": "/tmp/untrusted",
            }, clear=True), patch("os.getuid", return_value=1001), \
                 patch("os.geteuid", return_value=1001), \
                 patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir="/home/installer", pw_name="installer")), \
                 patch("os.execve", side_effect=fake_execve):
                with self.assertRaises(ProtocolReached):
                    runpy.run_path(str(entrypoint), run_name="__main__")
            with patch.object(node_exec_protocol, "require_account"), \
                 patch.object(node_exec_protocol, "configured_max_active", return_value=1):
                response = node_exec_protocol.serve_one(kwargs["input"], hostname="gway-001")
            return SimpleNamespace(stdout=json.dumps(response).encode())

        request = {"operation": "limits", "node": "gway-001", "request_id": RID}
        result = SSHTransport(self.node(), run=fake_ssh).invoke(request)
        self.assertEqual(result["concurrent_jobs_per_node"], 1)
        self.assertEqual(len(calls), 1)

        for bad in ("id", "gway-exec-protocol-v1; id"):
            with self.subTest(command=bad), \
                 patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": bad, "SSH_CONNECTION": "x"}, clear=True), \
                 patch("os.getuid", return_value=1001), \
                 patch("os.geteuid", return_value=1001), \
                 patch("os.execve") as execve:
                with self.assertRaises(SystemExit) as rejected:
                    runpy.run_path(str(entrypoint), run_name="__main__")
                self.assertEqual(rejected.exception.code, 1)
                execve.assert_not_called()

    def test_host_key_rotation_and_unsafe_permissions_fail_closed(self):
        with self.assertRaises(ValueError):
            self.node(host_key_sha256="b" * 64)
        self.identity.chmod(0o644)
        with self.assertRaises(PermissionError):
            self.node()
        self.identity.chmod(0o600)
        self.known.write_text(self.known.read_text() + self.known.read_text())
        with self.assertRaises(ValueError):
            self.node()

    def test_untrusted_ssh_user_and_wrong_node_denied(self):
        for user in ("root", "installer;id", "", "other@host"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                self.node(installer_user=user)
        called = []
        transport = SSHTransport(self.node(), run=lambda *a, **kw: called.append(a))
        with self.assertRaises(ValueError):
            transport.invoke({"operation": "limits", "node": "gway-002", "request_id": RID})
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
