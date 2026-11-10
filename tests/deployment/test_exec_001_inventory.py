"""Offline contract: only gway-001 selects the existing arthe operator via Ansible.

The production installer uses a transient local inventory, so a hostvar in
deployment.yml alone is insufficient. This suite tests the actual set_fact
task and preserves the explicit -e rollback override without touching hosts.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "ansible/inventory/deployment.yml"
MAIN = ROOT / "ansible/roles/gway_remote/tasks/main.yml"
SELECT = ROOT / "ansible/roles/gway_remote/tasks/node-exec-select.yml"
DEPLOY = ROOT / "deploy.sh"
TASK_NAME = "Select gway-001 executor from canonical inventory"


class PilotExecutorSelectionTests(unittest.TestCase):
    def test_transient_installer_uses_canonical_pilot_policy(self):
        installer = DEPLOY.read_text()
        role = MAIN.read_text()
        self.assertIn("-i 'gway_remote,' -c local", installer)
        self.assertIn('-e "gway_remote_runner_user=$(id -un)"', installer)
        self.assertEqual(role.count("- name: " + TASK_NAME), 1)
        self.assertIn("playbook_dir ~ '/inventory/deployment.yml'", role)
        self.assertIn("gway_remote_exec_run_user: arthe", INVENTORY.read_text())
        self.assertLess(role.index(TASK_NAME), role.index("node-exec-select.yml"))
        self.assertLess(role.index("node-exec-select.yml"), role.index("node-mcp-deploy.yml"))

    def test_no_new_authority_or_broad_account_switch(self):
        role = MAIN.read_text()
        selection = role.split("- name: " + TASK_NAME, 1)[1].split("\n- name:", 1)[0]
        self.assertIn("ansible.builtin.set_fact:", selection)
        self.assertIn("when: (ansible_hostname | default('')) == 'gway-001'", selection)
        self.assertNotIn("sudo", selection)
        self.assertNotIn("authorized_keys", selection)
        self.assertNotIn("gway_exec_relay_public_key", selection)
        select = SELECT.read_text()
        self.assertIn("gway_remote_exec_run_user == gway_remote_runner_user", select)
        self.assertIn("verify-exec-cutover.py", select)
        self.assertIn("verify-exec-relay-policy.py", select)
        self.assertIn("Restore previous restricted relay sudoers", select)
        self.assertIn("Restore previous executor identity configuration", select)

    def test_file_reader_sudo_is_exact_and_only_for_pilot(self):
        select = SELECT.read_text()
        self.assertIn("Permit only the isolated file reader as gway-exec", select)
        self.assertIn("arthe ALL=(gway-exec) NOPASSWD: /usr/bin/env PYTHONPATH=/opt/gway-remote /usr/bin/python3 -m gway_remote.node_file_reader", select)
        self.assertIn("validate: /usr/sbin/visudo -cf %s", select)
        self.assertIn("Reject unsafe pre-existing file reader policy", select)
        self.assertIn("Restore previous isolated file reader policy", select)
        self.assertIn("Remove newly installed isolated file reader policy after failure", select)
        self.assertLess(select.index("Permit only the isolated file reader as gway-exec"),
                        select.index("Update restricted SSH ForceCommand"))
        grant = select.split("    - name: Permit only the isolated file reader as gway-exec", 1)[1]
        grant = grant.split("\\n    - name:", 1)[0]
        self.assertIn("(ansible_hostname | default('')) == 'gway-001'", grant)
        self.assertIn("gway_remote_exec_run_user == 'arthe'", grant)

    @unittest.skipUnless(shutil.which("ansible-inventory"), "Ansible not installed")
    def test_effective_hostvars_are_limited_to_gway_001(self):
        for node in ("gway-001", "gway-002", "gway-004", "gway-005"):
            with self.subTest(node=node):
                result = subprocess.run(
                    ["ansible-inventory", "-i", str(INVENTORY), "--host", node],
                    capture_output=True, text=True, timeout=25, check=True,
                )
                vars = json.loads(result.stdout)
                if node == "gway-001":
                    self.assertEqual(vars["gway_remote_exec_run_user"], "arthe")
                else:
                    self.assertNotIn("gway_remote_exec_run_user", vars)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible not installed")
    def test_real_set_fact_is_pilot_only_and_rollback_override_works(self):
        # Render the exact deployed task in a disposable local playbook.
        # No become, SSH, service, credentials, or node files are used.
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML unavailable; exercised by the system-Ansible 2.12 CI job")

        role = yaml.safe_load(MAIN.read_text())
        selected = [task for task in role if task.get("name") == TASK_NAME]
        self.assertEqual(len(selected), 1)
        with tempfile.TemporaryDirectory(prefix="gway-exec-selection-") as tmp:
            directory = Path(tmp)
            (directory / "inventory").mkdir()
            shutil.copyfile(INVENTORY, directory / "inventory/deployment.yml")
            playbook = directory / "selection.yml"
            for hostname, rollback, expected in (
                ("gway-001", False, "arthe"),
                ("gway-002", False, "gway-exec"),
                ("gway-004", False, "gway-exec"),
                ("gway-001", True, "gway-exec"),
            ):
                with self.subTest(hostname=hostname, rollback=rollback):
                    payload = [{
                        "hosts": "localhost", "connection": "local",
                        "gather_facts": False,
                        "vars": {
                            "ansible_hostname": hostname,
                            "gway_remote_exec_run_user": "gway-exec",
                        },
                        "tasks": [
                            copy.deepcopy(selected[0]),
                            {"name": "Observe effective identity",
                             "ansible.builtin.debug": {
                                 "msg": "effective_executor={{ gway_remote_exec_run_user }}"
                             }},
                        ],
                    }]
                    playbook.write_text(yaml.safe_dump(payload, sort_keys=False))
                    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
                    if rollback:
                        command.extend(["-e", "gway_remote_exec_run_user=gway-exec"])
                    outcome = subprocess.run(
                        command, capture_output=True, text=True, timeout=60,
                    )
                    self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
                    self.assertIn("effective_executor=" + expected, outcome.stdout)


if __name__ == "__main__":
    unittest.main()
