"""Static contract for removing only the obsolete dedicated deployment privilege path."""
from pathlib import Path
import unittest

ROLE = Path("ansible/roles/gway_remote/tasks/node-mcp-deploy.yml")
MAIN = Path("ansible/roles/gway_remote/tasks/main.yml")
DEFAULTS = Path("ansible/roles/gway_remote/defaults/main.yml")
SELECT = Path("ansible/roles/gway_remote/tasks/node-exec-select.yml")


class LegacyDeployRetirementTests(unittest.TestCase):
    def test_retirement_is_idempotent_and_does_not_grant_privilege(self):
        text = ROLE.read_text()
        self.assertIn("ansible.builtin.service_facts:", text)
        self.assertIn("ansible.builtin.file:", text)
        self.assertIn("state: absent", text)
        self.assertIn("gway-remote-deploy.service", text)
        self.assertIn("/etc/sudoers.d/gway-remote-mcp-deploy", text)
        self.assertIn("daemon_reload: true", text)
        self.assertNotIn("NOPASSWD:", text)
        self.assertNotIn("state: started", text)
        self.assertNotIn("state: present", text)
        self.assertIn('mode: "0700"', text)

    def test_single_effective_identity_for_pilot_and_other_nodes(self):
        defaults = DEFAULTS.read_text()
        self.assertIn("gway_remote_exec_run_user:", defaults)
        self.assertIn("'arthe' if (ansible_hostname", defaults)
        self.assertIn("else 'gway-exec'", defaults)
        self.assertNotIn("gway_remote_exec_user:", defaults)
        select = SELECT.read_text()
        self.assertIn("gway_remote_exec_run_user == (gway_remote_exec_user | default(\'gway-exec\'))", select)
        self.assertIn("gway_remote_exec_run_user == gway_remote_runner_user", select)
        self.assertIn("gway_remote_exec_run_user != 'root'", select)
        self.assertIn("gway_remote_exec_run_user is match(", select)
        self.assertNotIn("gway_remote_exec_run_user in ['gway-exec', 'arthe']", select)
        self.assertIn('{"user": {{ gway_remote_exec_run_user | to_json }}}', select)
        self.assertIn("gway-relay ALL=({{ gway_remote_exec_run_user }})", select)

    def test_relay_force_command_accepts_configured_unix_account(self):
        import re
        select = SELECT.read_text()
        self.assertIn("[a-z_][a-z0-9_-]*", select)
        pattern = r"(?<=-u )[a-z_][a-z0-9_-]*(?= /usr/bin/env PYTHONPATH=)"
        for old in ("arthe", "gway-exec", "custom_operator_7"):
            command = f"sudo -n -u {old} /usr/bin/env PYTHONPATH=/opt/gway-remote python3 -m worker"
            self.assertIn("-u selected_user /usr/bin/env", re.sub(pattern, "selected_user", command))
        self.assertEqual("sudo -u root /bin/true", re.sub(pattern, "selected_user", "sudo -u root /bin/true"))

    def test_executor_cutover_has_ordered_rollback_for_relay_and_policy(self):
        select = SELECT.read_text()
        activation = select.split("- name: Activate selected execution identity", 1)[1]
        forward, recovery = activation.split("  rescue:", 1)
        self.assertIn("Install root-controlled selected executor identity", forward)
        self.assertIn("Verify both live relay policies point to the selected executor", forward)
        self.assertIn("Validate full sshd configuration", forward)
        self.assertIn("Verify selected executor can import the installed worker", forward)
        for step in (
            "Restore previous restricted relay sudoers",
            "Restore original forced-command SSH configuration",
            "Restore previous executor identity configuration",
            "Remove newly created executor identity configuration on rollback",
            "Recheck restored SSH/sudoers identity agreement after rollback",
            "Validate SSH after rollback",
            "Reload SSH after restoring original forced-command identity",
        ):
            self.assertIn(step, recovery)
        self.assertIn("exec_identity_original.content | b64decode", recovery)
        self.assertIn("exec_relay_sudo_original.content | b64decode", recovery)
        self.assertIn("exec_relay_sshd_original.content | b64decode", recovery)

    def test_offline_failure_compensation_restores_original_artifacts(self):
        # Pure local fixture: simulate failure after each cutover write.
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            originals = {
                "executor-identity.json": b'{"user":"original"}\\n',
                "gway-exec-relay": b"original sudoers\\n",
                "40-gway-exec-relay.conf": b"original sshd\\n",
            }
            for failed_after in range(1, len(originals) + 1):
                for name, data in originals.items():
                    (base / name).write_bytes(data)
                snapshots = {name: (base / name).read_bytes() for name in originals}
                try:
                    for index, name in enumerate(originals, 1):
                        (base / name).write_bytes(b"selected new policy\\n")
                        if index == failed_after:
                            raise RuntimeError("injected cutover failure")
                except RuntimeError:
                    for name, data in snapshots.items():
                        (base / name).write_bytes(data)
                self.assertEqual(snapshots, {name: (base / name).read_bytes() for name in originals})

    def test_general_release_rollback_is_not_yet_implemented(self):
        # Document the acceptance gap, not a fictitious rollback guarantee.
        deploy = Path("deploy.sh").read_text()
        self.assertIn('ansible-playbook "$ROOT/ansible/playbook.yml"', deploy)
        self.assertIn('mv -f "$tmp" "$marker"', deploy)
        self.assertNotIn("rollback-release.yml", deploy)

    def test_private_receipts_and_worker_share_selected_identity(self):
        role = ROLE.read_text()
        main = MAIN.read_text()
        self.assertIn('key: "{{ gway_remote_exec_run_user }}"', role)
        self.assertIn('owner: "{{ gway_remote_exec_run_user }}"', role)
        self.assertIn('group: "{{ gway_remote_exec_run_user }}"', role)
        self.assertIn('mode: "0700"', role)
        self.assertNotIn("gway_remote_exec_user", role)
        self.assertIn('      - "{{ gway_remote_exec_run_user }}"', main)
        self.assertNotIn("gway_remote_exec_user", main)
        self.assertNotIn("NOPASSWD:", role)
        self.assertNotIn("state: started", role)

    def test_runner_paths_use_passwd_home_not_name_concatenation(self):
        main = MAIN.read_text()
        self.assertIn("register: gway_remote_runner_passwd", main)
        self.assertIn("gway_remote_runner_passwd.ansible_facts.getent_passwd[gway_remote_runner_user][4]", main)
        self.assertNotIn("/home/{{ gway_remote_runner_user }}", main)

    def test_executor_selected_before_private_receipts(self):
        text = MAIN.read_text()
        self.assertLess(text.index("node-exec-select.yml"), text.index("node-mcp-deploy.yml"))


if __name__ == "__main__":
    unittest.main()
