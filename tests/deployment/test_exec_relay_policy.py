"""Consistency checks for the SSH forced command / sudoers cutover."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/verify-exec-relay-policy.py"
spec = importlib.util.spec_from_file_location("relay_identity_check", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def policies(user):
    command = module.PROTOCOL
    ssh = (
        "Match User gway-relay\n"
        "    AuthenticationMethods publickey\n"
        f"    ForceCommand /usr/bin/sudo -n -u {user} {command}\n"
    )
    sudo = f"gway-relay ALL=({user}) NOPASSWD: {command}\n"
    return ssh, sudo


class RelayPolicyTests(unittest.TestCase):
    def test_both_supported_users_have_same_fixed_protocol(self):
        for user in ("gway-exec", "arthe"):
            with self.subTest(user=user):
                ssh, sudo = policies(user)
                self.assertEqual(module.verify(ssh, sudo, user), user)

    def test_mismatched_users_are_rejected(self):
        ssh, _ = policies("arthe")
        _, sudo = policies("gway-exec")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            module.verify(ssh, sudo)

    def test_old_account_rejected_after_selected_identity_change(self):
        ssh, sudo = policies("gway-exec")
        with self.assertRaisesRegex(ValueError, "selected"):
            module.verify(ssh, sudo, "arthe")

    def test_extra_sudo_privilege_fails_closed(self):
        ssh, sudo = policies("arthe")
        with self.assertRaisesRegex(ValueError, "sudo_extra_rules"):
            module.verify(ssh, sudo + "gway-relay ALL=(root) NOPASSWD: ALL\n")

    def test_altered_protocol_rejected(self):
        ssh, sudo = policies("arthe")
        ssh = ssh.replace(module.PROTOCOL, "/bin/sh")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            module.verify(ssh, sudo)

    def test_duplicate_rules_rejected(self):
        ssh, sudo = policies("arthe")
        with self.assertRaisesRegex(ValueError, "ssh_forced_command_count"):
            module.verify(ssh + ssh, sudo)
        with self.assertRaisesRegex(ValueError, "sudo_rule_count"):
            module.verify(ssh, sudo + sudo)

    def test_protocol_diagnostics_do_not_echo_untrusted_policy(self):
        ssh, sudo = policies("arthe")
        with self.assertRaisesRegex(ValueError, "^ssh_protocol_mismatch$"):
            module.verify(ssh.replace(module.PROTOCOL, "/bin/sh SECRET"), sudo)
        with self.assertRaisesRegex(ValueError, "^sudo_protocol_mismatch$"):
            module.verify(ssh, sudo.replace(module.PROTOCOL, "/bin/sh SECRET"))

    def test_missing_expected_force_command_reports_specific_category(self):
        ssh, sudo = policies("arthe")
        with self.assertRaisesRegex(ValueError, "^ssh_forced_command_count$"):
            module.verify(ssh.replace("ForceCommand", "Comment"), sudo)


if __name__ == "__main__":
    unittest.main()
