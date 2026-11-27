import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_principal_admission import verify_admission
from gway_remote.mcp_federated_catalog import route_provider_call, FederationError
from gway_remote.mcp_node_providers import provider_call, NodeProviderError

class PrincipalAdmissionTests(unittest.TestCase):
    def test_real_bearer_principals(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry=BearerRegistry(Path(tmp)/"bearers.sqlite3")
            verifier=BearerVerifier(registry.path)
            first=registry.issue()
            second=registry.issue()
            delegated=registry.issue(parent_id=first.split("_")[1])
            self.assertEqual(verify_admission(verifier,first,"read"),first.split("_")[1])
            self.assertEqual(verify_admission(verifier,delegated,"read"),first.split("_")[1])
            self.assertNotEqual(verify_admission(verifier,second,"read"),first.split("_")[1])
            with self.assertRaises(PermissionError):
                verify_admission(verifier,first,"execute")
            registry.revoke(first.split("_")[1])
            with self.assertRaises(PermissionError):
                verify_admission(verifier,delegated,"read")

    def test_bound_route_does_not_fall_back(self):
        routes={"aeon_score__status":("gway-001","aeon_score","status","read",True)}
        legacy=Mock()
        bound=Mock(return_value={"ok":True})
        def call(args=None,**kw):
            return route_provider_call(routes,"aeon_score__status",args or {},
                 authorized_scope="read",invoke=legacy,**kw)
        with self.assertRaises(PermissionError): call(invoke_principal=bound)
        with self.assertRaises(FederationError): call(verified_principal="a"*24)
        with self.assertRaises(PermissionError):
            call({"principal":"b"*24},verified_principal="a"*24,invoke_principal=bound)
        self.assertEqual(call({"key":"c"*32},verified_principal="a"*24,invoke_principal=bound),{"ok":True})
        bound.assert_called_once_with("gway-001",{"provider":"aeon_score","tool":"status","arguments":{"key":"c"*32}},
                                     trusted_scope="read",verified_principal="a"*24)
        legacy.assert_not_called()

    def test_legacy_receiver_denies_bound_provider(self):
        with self.assertRaisesRegex(NodeProviderError,"principal_bound_transport_required"):
            provider_call([],provider="aeon_score",tool="status",arguments={},authorized_scope="execute")
