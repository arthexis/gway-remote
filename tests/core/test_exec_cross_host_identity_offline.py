"""Offline binding across root-pinned Watchtower login and node identity.

No SSH is opened and no execution work is submitted. The fake SSH boundary
reuses SSHTransport argument construction and real node require_account().
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote import node_exec_identity as identity
from gway_remote import node_exec_protocol as protocol
from gway_remote import node_exec_worker as worker
from gway_remote import watchtower_exec_service as service
from gway_remote.watchtower_exec_transport import SSHTransport, SSHTransportFailure

RID = "b" * 32


class CaptureRelay:
    def __init__(self, ledger, transport, *, enabled):
        self.transport = transport


class CrossHostInstallerBindingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        public = bytes(range(32))
        known = self.root / "known_hosts"
        private = self.root / "fake-key"
        known.write_text("gway-001 ssh-ed25519 " + base64.b64encode(public).decode() + "\n")
        private.write_text("fixture only: not an SSH private key\n")
        known.chmod(0o600)
        private.chmod(0o600)
        self.node_policy = self.root / "executor-identity.json"
        self.node_policy.write_text('{"user":"installer"}\n')
        self.node_policy.chmod(0o644)
        self.config = self.root / "execute.json"
        self.entry = dict(
            node="gway-001", address="10.42.0.2", ssh_host_alias="gway-001",
            known_hosts=str(known), identity_file=str(private),
            host_key_sha256=hashlib.sha256(public).hexdigest(),
            installer_user="installer",
        )
        self.write_config()
        self.inventory = {"nodes": [dict(
            node="gway-001", registered=True, identity_verified=True,
            address="10.42.0.2", execute_eligible=True, reachable="reachable",
            installer_binding={"user": "untrusted-enrollment-account"},
        )]}
        original_lstat = Path.lstat

        def metadata(path):
            info = original_lstat(path)
            if Path(path) in (self.config, self.node_policy):
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_size=info.st_size)
            return info

        self.patcher = patch.object(Path, "lstat", autospec=True, side_effect=metadata)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def write_config(self):
        self.config.write_text(json.dumps({"enabled": True, "nodes": [self.entry]}) + "\n")

    def load_pinned(self):
        with patch.object(service.node_registry_inventory, "load", return_value=self.inventory), \
             patch.object(service, "RequestLedger", return_value=object()), \
             patch.object(service, "DormantRelay", CaptureRelay), \
             patch.object(service, "AuthorizedExecution", side_effect=lambda ledger, unused, relay, **kw: relay):
            return service.load_service(self.config).transport.for_node("gway-001").node

    def invoke_readonly(self, *, remote_uid=1001):
        pinned = self.load_pinned()

        def passwd(user):
            return SimpleNamespace(pw_uid={"installer": 1001, "other": 1002}[user])

        def fake_ssh(argv, **kwargs):
            self.assertEqual(argv[argv.index("-l") + 1], pinned.installer_user)
            self.assertEqual(argv[-1], "gway-exec-protocol-v1")
            self.assertIn("-T", argv)
            self.assertIn("ClearAllForwardings=yes", argv)
            # Emulate the UID chosen by the SSH login, while the node reads its
            # OWN immutable identity, not the Watchtower or enrollment policy.
            with patch.object(worker, "selected_user", side_effect=lambda: identity.selected_user(self.node_policy)), \
                 patch.object(worker.pwd, "getpwnam", side_effect=passwd), \
                 patch.object(worker.os, "geteuid", return_value=remote_uid), \
                 patch.object(protocol, "configured_max_active", return_value=2):
                result = protocol.serve_one(kwargs["input"], hostname="gway-001")
            return SimpleNamespace(stdout=json.dumps(result).encode())

        return SSHTransport(pinned, run=fake_ssh).invoke({
            "operation": "limits", "node": "gway-001", "request_id": RID,
        })

    def test_root_operator_config_and_matching_installer_uid_allow_limits_only(self):
        result = self.invoke_readonly()
        self.assertEqual(result["concurrent_jobs_per_node"], 2)
        self.assertEqual(result["request_id"], RID)
        self.assertEqual(result["node"], "gway-001")

    def test_wrong_watchtower_login_is_refused_by_node_uid(self):
        self.entry["installer_user"] = "other"
        self.write_config()
        with self.assertRaises(SSHTransportFailure):
            self.invoke_readonly(remote_uid=1002)

    def test_node_policy_drift_is_refused_without_mutating_files(self):
        before = self.config.read_bytes()
        self.node_policy.write_bytes(b'{"user":"other"}\n')
        policy_before = self.node_policy.read_bytes()
        with self.assertRaises(SSHTransportFailure):
            self.invoke_readonly()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.node_policy.read_bytes(), policy_before)

    def test_wrong_effective_uid_denied_even_with_correct_login(self):
        with self.assertRaises(SSHTransportFailure):
            self.invoke_readonly(remote_uid=1002)

    def test_untrusted_config_modes_and_enrollment_login_are_not_authority(self):
        self.config.chmod(0o666)
        with self.assertRaises(PermissionError):
            self.load_pinned()
        self.config.chmod(0o600)
        self.node_policy.chmod(0o666)
        with self.assertRaises(SSHTransportFailure):
            self.invoke_readonly()
        self.node_policy.chmod(0o644)
        self.assertEqual(self.invoke_readonly()["concurrent_jobs_per_node"], 2)


if __name__ == "__main__":
    unittest.main()
