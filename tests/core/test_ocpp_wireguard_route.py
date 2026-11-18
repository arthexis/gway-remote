"""Hermetic route-selection tests; no WireGuard, firewall or network I/O."""
import json
import subprocess
import unittest
from unittest.mock import Mock

from gway_remote.ocpp_wireguard_route import (
    SCHEMA, classify_route, inspect_route, main,
)

DEST = "10.80.0.3"


def route(*, dev="gway", gateway=None, dst=DEST, **extra):
    entry = {"dst": dst, "dev": dev, **extra}
    if gateway is not None:
        entry["gateway"] = gateway
    return json.dumps([entry])


class OcppWireguardRouteTests(unittest.TestCase):
    def test_vpn_route_selected_does_not_claim_end_to_end(self):
        result = classify_route(route(dev="gway", prefsrc="10.80.0.2"), DEST)
        self.assertEqual(result, {
            "schema": SCHEMA, "selection": "via_hub", "interface": "gway",
            "via_gateway": False, "reason": "route_selected",
        })

    def test_direct_ethernet_and_wifi_are_local_candidates(self):
        for dev in ("eth0", "wlan0", "wlan1"):
            with self.subTest(dev=dev):
                result = classify_route(route(dev=dev), DEST)
                self.assertEqual(result["selection"], "via_lan")
                self.assertFalse(result["via_gateway"])

    def test_physical_default_gateway_is_unexpected(self):
        result = classify_route(route(dev="eth0", gateway="192.0.2.1"), DEST)
        self.assertEqual(result["selection"], "unexpected")
        self.assertTrue(result["via_gateway"])

    def test_wrong_interface_and_wg_gateway_fail_closed(self):
        for payload in (
            route(dev="tun0"),
            route(dev="lo"),
            route(dev="gway", gateway="10.80.0.1"),
            route(dev="gway", type="blackhole"),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(classify_route(payload, DEST)["selection"], "unexpected")

    def test_mismatch_missing_and_ambiguous_are_unknown(self):
        for payload, reason in (
            (route(dst="10.80.0.4"), "destination_mismatch"),
            (json.dumps([{"dst": DEST}]), "missing_interface"),
            ("[]", "ambiguous_route"),
            (json.dumps([{"dst": DEST, "dev": "gway"}] * 2), "ambiguous_route"),
            ("not-json", "invalid_route_json"),
            ("x" * 65537, "invalid_route_json"),
        ):
            with self.subTest(reason=reason):
                result = classify_route(payload, DEST)
                self.assertEqual(result["selection"], "unknown")
                self.assertEqual(result["reason"], reason)

    def test_rejects_non_unicast_or_non_literal_ip(self):
        for destination in ("0.0.0.0", "127.0.0.1", "224.0.0.1",
                            "169.254.1.2", "255.255.255.255",
                            "example.test", "10.80.0.0/24", "10.80.0.3; true"):
            with self.subTest(destination=destination):
                result = classify_route(route(), destination)
                self.assertEqual(result["selection"], "unknown")
                self.assertEqual(result["reason"], "invalid_destination")

    def test_invalid_gateway_is_unknown(self):
        for gateway in ("not-an-ip", "::1", 123):
            with self.subTest(gateway=gateway):
                self.assertEqual(
                    classify_route(route(gateway=gateway), DEST)["reason"],
                    "invalid_gateway",
                )

    def test_inspect_issues_only_bounded_read_only_command(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=route(), stderr=""))
        report = inspect_route(DEST, run=run)
        self.assertEqual(report["selection"], "via_hub")
        run.assert_called_once_with(
            ["ip", "-4", "-j", "route", "get", DEST],
            capture_output=True, text=True, timeout=3, check=False,
        )

    def test_no_probes_when_invalid_and_unknown_on_command_failure(self):
        run = Mock()
        self.assertEqual(inspect_route("bad-host", run=run)["selection"], "unknown")
        run.assert_not_called()
        run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="restricted")
        self.assertEqual(inspect_route(DEST, run=run)["selection"], "unknown")
        run.side_effect = subprocess.TimeoutExpired("ip", 3)
        self.assertEqual(inspect_route(DEST, run=run)["selection"], "unknown")

    def test_cli_exit_code_matches_known_vs_unknown(self):
        # No live network: empty output is deliberately unknown.
        from unittest.mock import patch
        with patch("gway_remote.ocpp_wireguard_route.inspect_route",
                   return_value={"selection": "unknown"}):
            with patch("builtins.print"):
                self.assertEqual(main([DEST]), 2)
        with patch("gway_remote.ocpp_wireguard_route.inspect_route",
                   return_value={"selection": "via_hub"}):
            with patch("builtins.print"):
                self.assertEqual(main([DEST]), 0)


if __name__ == "__main__":
    unittest.main()
