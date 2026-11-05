"""CLI contract for SSH host key output and Watchtower attestation guidance."""
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import __main__ as cli


class TestHostKeyCLI(unittest.TestCase):
    def test_local_key_uses_existing_validator(self):
        # The CLI must reuse the bootstrap's validated public-key reader,
        # never print a private key or create a new host identity.
        with patch("gway_remote.wireguard_satellite._ssh_host_public_key",
                   return_value="ssh-ed25519 AAAATEST") as read_key:
            with patch("sys.argv", ["gway-remote", "host-key"]):
                with patch("builtins.print") as output:
                    cli.main()
        read_key.assert_called_once_with()
        output.assert_called_once_with("ssh-ed25519 AAAATEST")
