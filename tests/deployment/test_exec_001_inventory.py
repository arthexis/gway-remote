"""#617 regression: the old 001 inventory is not executor identity authority.

New and existing installations share a root-owned node-local identity; an
operator may not force an upgrade migration through an inventory hostvar.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "ansible/roles/gway_remote/tasks/main.yml"
SELECT = ROOT / "ansible/roles/gway_remote/tasks/node-exec-select.yml"
DEFAULTS = ROOT / "ansible/roles/gway_remote/defaults/main.yml"
DEPLOY = ROOT / "deploy.sh"


class ProvisionedIdentityAnsibleTests(unittest.TestCase):
    def test_runner_is_real_nonroot_deploy_invoker(self):
        deploy = DEPLOY.read_text()
        self.assertIn('if [ "$(id -u)" -eq 0 ]', deploy)
        self.assertIn('-e "gway_remote_runner_user=$(id -un)"', deploy)
        self.assertIn("gway_remote_runner_user: \"\"", DEFAULTS.read_text())
        self.assertIn("gway_remote_executor_override: \"\"", DEFAULTS.read_text())

    def test_persisted_policy_precedes_mutation_and_inventory_pilot_is_not_authority(self):
        role = MAIN.read_text()
        self.assertIn("scripts/resolve-executor-user.py", role)
        self.assertIn("gway_remote_resolved_executor_user", role)
        self.assertLess(role.index("Resolve node-local executor identity before provisioning"),
                        role.index("node-exec-prepare.yml"))
        self.assertLess(role.index("gway_remote_resolved_executor_user"),
                        role.index("node-exec-select.yml"))
        self.assertNotIn("Select gway-001 executor from canonical inventory", role)
        self.assertNotIn("gway_remote_exec_run_user: \"{{ (lookup('file'", role)

    def test_only_preflight_selection_can_activate_guarded_identity(self):
        select = SELECT.read_text()
        self.assertIn("gway_remote_exec_run_user == gway_remote_resolved_executor_user", select)
        self.assertIn("verify-exec-cutover.py", select)
        self.assertIn("verify-exec-relay-policy.py", select)
        self.assertIn("Restore previous restricted relay sudoers", select)
        self.assertIn("Restore previous executor identity configuration", select)
        self.assertIn('mode: \'0700\'', select)
        self.assertIn('/var/lib/gway-remote-exec-{{ gway_remote_exec_run_user }}', select)

    def test_file_reader_exception_stays_pilot_only(self):
        select = SELECT.read_text()
        self.assertIn("{{ gway_remote_exec_run_user }} ALL=(gway-exec) NOPASSWD:", select)
        section = select.split("    - name: Permit only the isolated file reader as gway-exec", 1)[1]
        section = section.split("    - name:", 1)[0]
        self.assertIn("(ansible_hostname | default('')) == 'gway-001'", section)
        self.assertIn("gway_remote_exec_run_user != gway_remote_exec_user", section)

    def test_no_appliance_watch_or_new_ssh_transport(self):
        role = MAIN.read_text()
        self.assertNotIn("- name: Enable periodic GWay Remote appliance watch", role)
        self.assertNotIn("- name: Install appliance watch systemd units", role)
        self.assertIn("node-exec-relay.yml", role)
        self.assertIn("verify_node_worker_import; then", DEPLOY.read_text())


if __name__ == "__main__":
    unittest.main()
