"""Regression guard for gway-001 forced-command SSH relay configuration.

The deployed Pi's OpenSSH rejects PermitUserEnvironment inside Match User.
Keep the restriction via the globally configured sshd policy, and verify the
full sshd configuration before reload as well as the copied fragment.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "ansible/roles/gway_remote/tasks/node-exec-relay.yml"


class RelayOpenSSHCompatibilityTests(unittest.TestCase):
    def test_match_block_uses_supported_restrictions(self):
        text = ROLE.read_text(encoding="utf-8")
        block = text.split("      Match User gway-relay\n", 1)[1].split("    validate:", 1)[0]
        self.assertNotIn("PermitUserEnvironment", block)
        for required in (
            "AuthenticationMethods publickey",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            "PermitTTY no",
            "DisableForwarding yes",
            "AllowAgentForwarding no",
            "AllowTcpForwarding no",
            "X11Forwarding no",
            "PermitTunnel no",
            "AuthorizedKeysFile /var/lib/gway-relay/.ssh/authorized_keys",
            "ForceCommand /usr/bin/sudo -n -u gway-exec",
        ):
            self.assertIn(required, block)

    def test_validate_fragment_and_full_daemon_before_reload(self):
        text = ROLE.read_text(encoding="utf-8")
        self.assertIn("validate: /usr/sbin/sshd -t -f %s", text)
        full = text.index("- name: Validate effective SSH daemon configuration")
        reload = text.index("- name: Reload SSH daemon with forced-command policy")
        self.assertLess(full, reload)
        self.assertIn("argv: [/usr/sbin/sshd, -t]", text[full:reload])
        self.assertIn("changed_when: false", text[full:reload])
        self.assertIn("when: gway_relay_sshd_conf.changed", text[reload:])


if __name__ == "__main__":
    unittest.main()
