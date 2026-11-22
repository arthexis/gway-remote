"""A bad or unavailable pin must not disable unrelated MCP nodes."""
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gway_remote.mcp_gateway_federation import FederatedProviders
from gway_remote.mcp_provider_transport import ProviderTransport
from gway_remote.watchtower_exec_service import NodeUnavailable, load_service
from tests.helpers.mcp_provider import provider_reply


def entry(name):
    return {"node": name, "address": "10.0.0." + name[-1],
            "ssh_host_alias": name, "known_hosts": "/private/hosts",
            "identity_file": "/private/key", "host_key_sha256": "a" * 64,
            "remote_user": "gway-relay"}


def row(e, **changes):
    return {"node": e["node"], "address": e["address"], "registered": True,
            "identity_verified": True, "execute_eligible": True,
            "reachable": "reachable", **changes}


class IsolationTests(unittest.TestCase):
    def test_degraded_start_live_provider_checks_and_recovery(self):
        first, second = entry("gway-001"), entry("gway-004")
        rows = [row(first), row(second, reachable="unknown")]
        sent = []
        def pin(**kw):
            return SimpleNamespace(**kw)
        def send(node):
            def invoke(payload):
                sent.append((node.node, payload["operation"]))
                return {"node": node.node, "request_id": payload["request_id"],
                        "result": provider_reply(node.node)}
            return SimpleNamespace(invoke=invoke)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "execute.json"
            path.write_text(json.dumps({"enabled": True, "nodes": [first, second]}))
            trusted = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=100)
            with patch.object(Path, "lstat", return_value=trusted), \
                 patch("gway_remote.watchtower_exec_service.RequestLedger"), \
                 patch("gway_remote.watchtower_exec_service.PinnedNode", side_effect=pin), \
                 patch("gway_remote.watchtower_exec_service.SSHTransport", side_effect=send), \
                 patch("gway_remote.node_registry_inventory.load", side_effect=lambda: {"nodes": rows}):
                service = load_service(path)
                transport = service.relay.transport
                provider = ProviderTransport(transport)
                gateway = FederatedProviders(transport=provider, nodes=lambda: tuple(transport.transports))
                tools, routes = gateway.discover()
                self.assertEqual(routes["odoo__list"][0], "gway-001")
                with self.assertRaises(NodeUnavailable):
                    provider.invoke("gway-004", {"operation": "provider_list"}, trusted_scope="read")
                rows[1] = row(second)
                _, routes = gateway.discover()
                self.assertTrue(any(route[0] == "gway-004" for route in routes.values()))
                # A route discovered while eligible cannot be used after revocation.
                rows[1] = row(second, execute_eligible=False)
                calls_before = len(sent)
                with self.assertRaises(NodeUnavailable):
                    provider.invoke("gway-004", {"operation": "provider_call", "provider": "odoo",
                        "tool": "update", "arguments": {}}, trusted_scope="execute")
                self.assertEqual(len(sent), calls_before)
                for key, bad in (("identity_verified", False), ("execute_eligible", False),
                                 ("registered", False), ("address", "10.0.0.99"),
                                 ("reachable", "unknown")):
                    rows[1] = row(second, **{key: bad})
                    with self.subTest(key=key), self.assertRaises(NodeUnavailable):
                        provider.invoke("gway-004", {"operation": "provider_list"}, trusted_scope="read")
                rows[1] = row(second)
                with patch("gway_remote.node_registry_inventory.load", side_effect=ValueError("private error")):
                    with self.assertRaisesRegex(NodeUnavailable, "^node unavailable$"):
                        provider.invoke("gway-004", {"operation": "provider_list"}, trusted_scope="read")

    def test_invalid_private_pin_is_isolated(self):
        from gway_remote.watchtower_exec_service import CheckedNodeTransport
        with patch("gway_remote.watchtower_exec_service.PinnedNode", side_effect=PermissionError("secret path")):
            with self.assertRaisesRegex(NodeUnavailable, "^node unavailable$"):
                CheckedNodeTransport(entry("gway-004")).invoke({})


if __name__ == "__main__":
    unittest.main()
