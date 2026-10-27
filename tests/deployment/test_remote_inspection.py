"""Inspection must reject unapproved nodes and untrusted registry material."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.remote_inspection import inspect


class RemoteInspectionTests(unittest.TestCase):
    def test_unapproved_never_reads_files(self):
        with self.assertRaisesRegex(ValueError, "not approved"):
            inspect("gway-005", approved=set(), registry_path="/does/not/exist")

    def test_strict_bastion_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            config = Path(directory) / "ssh.conf"
            registry.write_text(json.dumps({"schema": 1, "nodes": [
                {"node": "gway-004", "address": "10.90.0.4/32", "state": "active"}]}))
            config.write_text("Host gway-004\n  ProxyJump gelectriic.com\n")
            registry.chmod(0o600)
            config.chmod(0o600)
            with patch("gway_remote.remote_inspection.inspect_ssh",
                       return_value={"ssh": "verified"}) as ssh:
                result = inspect("gway-004", approved={"gway-004"},
                                 registry_path=registry, ssh_config=config)
            self.assertEqual(result["ssh"], "verified")
            ssh.assert_called_once_with("gway-004")

    def test_world_writable_registry_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            registry.write_text("{}")
            registry.chmod(0o666)
            with self.assertRaisesRegex(ValueError, "permissions"):
                inspect("gway-004", approved={"gway-004"}, registry_path=registry)
