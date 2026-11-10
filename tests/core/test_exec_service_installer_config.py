"""Offline checks for root-configured SSH login independent of enrollment."""
from pathlib import Path
import tempfile
import unittest
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

    def test_enrollment_binding_is_not_ssh_login_source(self):
        source = Path(service.__file__).read_text()
        self.assertNotIn('get("installer_binding")', source)
        self.assertIn('entry["installer_user"]', source)
        self.assertIn('n["identity_verified"] is True', source)
        self.assertIn('n["execute_eligible"] is True', source)

if __name__ == "__main__":
    unittest.main()
