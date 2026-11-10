"""Offline checks for root-configured SSH login independent of enrollment."""
from pathlib import Path
import tempfile
import unittest
import base64
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from gway_remote import watchtower_exec_service as service

class ServiceIdentityTests(unittest.TestCase):
    def test_missing_installer_login_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "execute.json"
            path.write_text('{"enabled":true,"node":"gway-001","address":"10.42.0.1",'
                            '"ssh_host_alias":"gway-001","known_hosts":"/tmp/missing",'
                            '"identity_file":"/tmp/missing","host_key_sha256":"' + "a"*64 + '"}')
            with patch.object(service.os, "geteuid", return_value=0), patch.object(
                service.node_registry_inventory, "load", side_effect=AssertionError("inventory accessed")
            ):
                with self.assertRaises((ValueError, PermissionError)):
                    service.load_service(path)

    def test_root_config_and_attested_node_resolve_pinned_ssh_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = bytes(range(32))
            digest = hashlib.sha256(key).hexdigest()
            known = root / "known_hosts"
            private = root / "identity"
            known.write_text("gway-001 ssh-ed25519 " + base64.b64encode(key).decode() + "\n")
            private.write_text("offline test only")
            known.chmod(0o600)
            private.chmod(0o600)
            config = root / "execute.json"
            entry = dict(node="gway-001", address="10.42.0.2",
                         ssh_host_alias="gway-001", known_hosts=str(known),
                         identity_file=str(private), host_key_sha256=digest,
                         installer_user="installer")
            config.write_text(json.dumps(dict(enabled=True, nodes=[entry])))
            original_lstat = Path.lstat
            def root_config_lstat(path):
                info = original_lstat(path)
                if Path(path) == config:
                    return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_size=info.st_size)
                return info
            inventory = {"nodes": [dict(node="gway-001", registered=True,
                                        identity_verified=True, address="10.42.0.2",
                                        execute_eligible=True, reachable="reachable",
                                        installer_binding={"user": "wrong", "state": "active"})]}
            class CaptureRelay:
                def __init__(self, ledger, transport, *, enabled):
                    self.transport = transport
            with patch.object(Path, "lstat", root_config_lstat), \
                 patch.object(service.node_registry_inventory, "load", return_value=inventory), \
                 patch.object(service, "RequestLedger", return_value=object()), \
                 patch.object(service, "DormantRelay", CaptureRelay), \
                 patch.object(service, "AuthorizedExecution", side_effect=lambda ledger, unused, relay, **kw: relay):
                relay = service.load_service(config)
            pinned = relay.transport.for_node("gway-001").node
            self.assertEqual(pinned.installer_user, "installer")
            self.assertEqual(pinned.host_key_sha256, digest)
            entry["installer_user"] = "root"
            config.write_text(json.dumps(dict(enabled=True, nodes=[entry])))
            with patch.object(Path, "lstat", root_config_lstat), \
                 patch.object(service.node_registry_inventory, "load", return_value=inventory):
                with self.assertRaises(PermissionError):
                    service.load_service(config)

    def test_enrollment_binding_is_not_ssh_login_source(self):
        source = Path(service.__file__).read_text()
        self.assertNotIn('get("installer_binding")', source)
        self.assertIn('entry["installer_user"]', source)
        self.assertIn('n["identity_verified"] is True', source)
        self.assertIn('n["execute_eligible"] is True', source)

if __name__ == "__main__":
    unittest.main()
