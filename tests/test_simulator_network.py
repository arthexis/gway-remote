import unittest
from unittest.mock import patch

from gway_remote import simulator_network as network
from gway_remote import mobile


class SimulatorDiscoveryTests(unittest.TestCase):
    def test_discovery_filters_neighbor_states_and_off_subnet(self):
        def ip(*args):
            if args[0] == "address":
                return [{"addr_info": [{"family": "inet", "local": "192.168.50.1", "prefixlen": 24}]}]
            return [{"dst": "192.168.50.2", "state": "REACHABLE"},
                    {"dst": "192.168.50.3", "state": "FAILED"},
                    {"dst": "10.0.0.2", "state": "REACHABLE"}]
        with patch.object(network, "_ip", side_effect=ip), patch.object(
                network, "_reachable", return_value=True) as probe:
            result = network.discover()
        self.assertEqual(len(result["peers"]), 1)
        self.assertEqual(result["peers"][0]["host"], "192.168.50.2")
        probe.assert_called_once_with("192.168.50.2", 9000)

    def test_manual_host_must_be_on_wired_subnet(self):
        with patch.object(network, "_networks", return_value=(
                ["192.168.50.1"], [network.ipaddress.ip_network("192.168.50.0/24")])):
            for host in ("127.0.0.1", "10.0.0.5", "example.com"):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    network.discover(host=host)
            with patch.object(network, "_reachable", return_value=False):
                result = network.discover(host="192.168.50.2", port=9001)
                self.assertFalse(result["peers"][0]["tcp_reachable"])

    def test_invalid_arguments_do_not_execute(self):
        for arguments in ({"port": True}, {"port": 65536}, {"command": "shell"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                mobile.execute("simulator-discover", arguments)

    def test_command_is_declared(self):
        entry = next(x for x in mobile.commands() if x["name"] == "simulator-discover")
        self.assertTrue(entry["read_only"])
