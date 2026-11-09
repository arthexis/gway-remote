"""Offline pinned SSH identities and multi-node provider routing."""
import base64
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote.mcp_provider_transport import ProviderTransport
from gway_remote.watchtower_exec_transport import PinnedNode, SSHTransport, MultiNodeTransport


class PinnedReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = base64.b64encode(b"offline-test-host-key").decode()
        self.fingerprint = hashlib.sha256(b"offline-test-host-key").hexdigest()

    def node(self, name, user, *, suffix, fingerprint=None, mode=0o600):
        host = self.root / (name + "-" + suffix + ".hosts")
        key = self.root / (name + "-" + suffix + ".identity")
        host.write_text(f"{name} ssh-ed25519 {self.key}\n")
        key.write_text("placeholder-not-a-real-private-key")
        host.chmod(mode)
        key.chmod(mode)
        return PinnedNode(name, "10.90.0.2", name, host, key,
                          fingerprint or self.fingerprint, user)

    def test_pins_reject_wrong_fingerprint_and_insecure_permissions(self):
        with self.assertRaises(ValueError):
            self.node("gway-001", "gway-read", suffix="wrong", fingerprint="0" * 64)
        with self.assertRaises(PermissionError):
            self.node("gway-001", "gway-read", suffix="public", mode=0o644)

    def test_strict_multinode_read_never_uses_execute(self):
        reads, executes = {}, {}
        for name in ("gway-001", "gway-002"):
            read_node = self.node(name, "gway-read", suffix="read")
            exec_node = self.node(name, "gway-relay", suffix="exec")
            def runner(argv, *, input, capture_output, timeout, check):
                import json
                request = json.loads(input)
                return SimpleNamespace(stdout=json.dumps({
                    "node": request["node"], "request_id": request["request_id"],
                    "result": {"ok": True}}).encode())
            reads[name] = SSHTransport(read_node, run=runner)
            executes[name] = SSHTransport(exec_node, run=runner)
        transport = ProviderTransport(MultiNodeTransport(executes),
                                      read_transport=MultiNodeTransport(reads),
                                      require_read_identity=True)
        request = {"operation": "provider_call", "provider": "diagnostics",
                   "tool": "hardware", "arguments": {}}
        for name in reads:
            self.assertEqual(transport.invoke(name, request, trusted_scope="read"),
                             {"ok": True})
        with self.assertRaises(PermissionError):
            transport.invoke("gway-003", request, trusted_scope="read")

    def test_strict_read_rejects_replayed_or_wrong_node_reply(self):
        import json
        read_node = self.node("gway-001", "gway-read", suffix="read")
        exec_node = self.node("gway-001", "gway-relay", suffix="exec")
        for wrong in ("node", "request_id"):
            def runner(argv, *, input, capture_output, timeout, check):
                request = json.loads(input)
                return SimpleNamespace(stdout=json.dumps({
                    "node": "gway-002" if wrong == "node" else request["node"],
                    "request_id": "0" * 32 if wrong == "request_id" else request["request_id"],
                    "result": {}}).encode())
            provider = ProviderTransport(SSHTransport(exec_node, run=runner),
                read_transport=SSHTransport(read_node, run=runner),
                require_read_identity=True)
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                provider.invoke("gway-001", {"operation": "provider_list"},
                                trusted_scope="read")

    def test_read_timeout_is_not_retried_over_execute(self):
        read_node = self.node("gway-001", "gway-read", suffix="read")
        exec_node = self.node("gway-001", "gway-relay", suffix="exec")
        calls = []
        def timeout(argv, *, input, capture_output, timeout, check):
            calls.append("read")
            raise subprocess.TimeoutExpired(argv, timeout)
        def execute(argv, *, input, capture_output, timeout, check):
            calls.append("execute")
            raise AssertionError("execute fallback")
        provider = ProviderTransport(SSHTransport(exec_node, run=execute),
            read_transport=SSHTransport(read_node, run=timeout),
            require_read_identity=True)
        with self.assertRaises(subprocess.TimeoutExpired):
            provider.invoke("gway-001", {"operation": "provider_list"},
                            trusted_scope="read")
        self.assertEqual(calls, ["read"])

    def test_strict_read_rejects_different_pinned_endpoint(self):
        read_node = self.node("gway-001", "gway-read", suffix="read")
        exec_node = self.node("gway-001", "gway-relay", suffix="exec")
        from dataclasses import replace
        cases = [
            replace(read_node, wireguard_address="10.90.0.3"),
            replace(read_node, ssh_host_alias="other-node"),
        ]
        for altered in cases:
            with self.subTest(altered=altered), self.assertRaises(PermissionError):
                ProviderTransport(SSHTransport(exec_node),
                    read_transport=SSHTransport(altered),
                    require_read_identity=True).invoke("gway-001",
                        {"operation": "provider_list"}, trusted_scope="read")

    def test_strict_read_denies_unenrolled_node_without_execute_fallback(self):
        read_node = self.node("gway-001", "gway-read", suffix="read")
        exec_node = self.node("gway-001", "gway-relay", suffix="exec")
        execute = MultiNodeTransport({"gway-001": SSHTransport(exec_node)})
        read = MultiNodeTransport({"gway-001": SSHTransport(read_node)})
        provider = ProviderTransport(execute, read_transport=read,
                                     require_read_identity=True)
        with self.assertRaises(PermissionError):
            provider.invoke("gway-002", {"operation": "provider_list"},
                            trusted_scope="read")


if __name__ == "__main__":
    unittest.main()
