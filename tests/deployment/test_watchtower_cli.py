import sys
import unittest
from unittest.mock import ANY, patch

from gway_remote import __main__ as cli


class WatchtowerCliTests(unittest.TestCase):
    def test_active_serve_constructs_provisioner_without_shadowing_os(self):
        argv = [
            "gway-remote", "watchtower", "serve",
            "--ledger", "/var/lib/gway-remote/watchtower/ledger.sqlite3",
            "--network", "10.90.0.0/24",
            "--gateway", "10.90.0.1",
            "--config", "/etc/wireguard/gway.conf",
            "--backup-dir", "/var/backups/gway-remote-watchtower/enrollment",
            "--public-url", "https://register.gelectriic.com",
            "--wireguard-endpoint", "register.gelectriic.com:51820",
        ]
        with patch.object(sys, "argv", argv), \
                patch.object(cli.os, "geteuid", return_value=0), \
                patch("gway_remote.watchtower_enrollment.Ledger") as ledger, \
                patch("gway_remote.watchtower_enrollment.Provisioner") as provisioner, \
                patch("gway_remote.watchtower_enrollment.SubprocessWireGuard") as wireguard, \
                patch("gway_remote.watchtower_enrollment.serve") as serve:
            cli.main()

        ledger.assert_called_once()
        wireguard.assert_called_once_with()
        provisioner.assert_called_once_with(
            ledger.return_value,
            ANY,
            ANY,
            wireguard.return_value,
        )
        serve.assert_called_once_with(
            provisioner.return_value,
            host="127.0.0.1",
            port=8788,
            public_url="https://register.gelectriic.com",
            wireguard_endpoint="register.gelectriic.com:51820",
        )


if __name__ == "__main__":
    unittest.main()
