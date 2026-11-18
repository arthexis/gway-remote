"""Offline, no-node contract tests for #614 gway-002-only SSH relay preparation."""
from pathlib import Path
import unittest

try:
    import yaml
except ImportError:
    yaml = None


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "ansible/playbooks/gway002-relay-only.yml"
ROLE = ROOT / "ansible/roles/gway_remote/tasks/node-exec-relay.yml"
INVENTORY = ROOT / "ansible/inventory/deployment.yml"
DOC = ROOT / "docs/gway002-relay-acceptance.md"


@unittest.skipIf(yaml is None, "PyYAML unavailable")
class Gway002RelayOnlyContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playbook = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]
        cls.tasks = cls.playbook["tasks"]
        cls.role = yaml.safe_load(ROLE.read_text(encoding="utf-8"))

    def task(self, name):
        found = [task for task in self.tasks if task.get("name") == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def test_local_exact_node_and_no_implicit_apply(self):
        self.assertEqual(self.playbook["hosts"], "localhost")
        self.assertEqual(self.playbook["connection"], "local")
        self.assertFalse(self.playbook["become"])
        self.assertIs(self.playbook["vars"]["gway_002_relay_apply"], False)
        assert_conditions = self.task("Refuse other nodes, identities, or implicit authorization")[
            "ansible.builtin.assert"]["that"]
        for required in (
            "ansible_hostname == 'gway-002'",
            "inventory_hostname == 'localhost'",
            "lookup('pipe', 'id -un') == 'arthe'",
            "gway_002_relay_apply | type_debug == 'bool'",
            "gway_002_expected_executor_user in ['gway-exec', 'arthe']",
        ):
            self.assertIn(required, assert_conditions)
        self.assertTrue(any("I_ACCEPT_GWAY_002_RELAY_ONLY" in c
                            for c in assert_conditions))

    def test_trusted_public_key_only_and_no_credential_distribution(self):
        text = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("relay_public_key_file.stat.checksum == gway_002_relay_public_key_sha256", text)
        self.assertIn("relay_public_key_file.stat.pw_name == 'root'", text)
        self.assertIn("relay_selected_account.stdout == gway_002_expected_executor_user", text)
        self.assertIn("gway_002_relay_public_key_path == '/etc/gway-remote/approved-watchtower-relay.pub'", text)
        self.assertIn("relay_key_parent.stat.pw_name == 'root'", text)
        self.assertIn("relay_key_parent.stat.mode in", text)
        self.assertIn("from gway_remote.node_exec_identity import selected_user", text)
        self.assertIn("follow: false", text)
        self.assertIn("no_log: true", text)
        self.assertNotIn("ssh-keyscan", text)
        self.assertNotIn("StrictHostKeyChecking=no", text)
        self.assertNotIn("/etc/gway-remote/deployment.yml", text)
        self.assertNotIn("ansible.builtin.git:", text)
        self.assertNotIn("ansible.builtin.apt:", text)
        self.assertNotIn("ansible.builtin.user:", text)
        self.assertNotIn("ansible.builtin.group:", text)

    def test_only_existing_restricted_receiver_recipe_under_apply_gate(self):
        task = self.task("Converge only existing restricted SSH relay recipe with recovery")
        self.assertEqual(task["when"], "gway_002_relay_apply | bool")
        self.assertTrue(task["become"])
        block = task["block"]
        self.assertGreaterEqual(len(block), 2)
        included = next(x["ansible.builtin.include_tasks"] for x in block if "ansible.builtin.include_tasks" in x)
        self.assertEqual(included, "../roles/gway_remote/tasks/node-exec-relay.yml")
        names = {task.get("name") for task in self.role}
        for name in (
            "Install dedicated SSHD Match block with forced protocol only",
            "Install single SSH key for fixed-command relay",
            "Permit ONLY the fixed non-root protocol transition",
        ):
            self.assertIn(name, names)
        rescue = task["rescue"]
        self.assertTrue(any("recover" in str(x.get("ansible.builtin.command", {}).get("argv", [])) for x in rescue))
        self.assertTrue(any("ansible.builtin.systemd" in x for x in rescue))
        self.assertTrue(any("ansible.builtin.fail" in x for x in rescue))
        self.assertEqual(
            {x["ansible.builtin.systemd"]["name"]
             for x in rescue if "ansible.builtin.systemd" in x}, {"ssh"})

    def test_journal_gate_precedes_mutation_and_fail_closed(self):
        prepare = self.task("Create durable protected journal before any change")
        self.assertEqual(prepare["when"], "gway_002_relay_apply | bool")
        self.assertIn("prepare", prepare["ansible.builtin.command"]["argv"])
        self.assertIn("gway002_relay_journal.py", str(prepare))
        self.assertIn("Refuse to create accounts or directories outside the file journal",
                      {t.get("name") for t in self.tasks})

    def test_inventory_is_still_production_and_deny_deploy(self):
        data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
        production = data["all"]["children"]["production"]["hosts"]["gway-002"]
        self.assertEqual(production["remote_managed_repositories"], [])
        self.assertNotIn("gway-002", data["all"]["children"]["controller"]["hosts"])
        self.assertNotIn("gway-002", data["all"]["children"]["quality"]["hosts"])

    def test_docs_do_not_claim_live_acceptance_or_auto_activation(self):
        text = DOC.read_text(encoding="utf-8")
        for phrase in (
            "NOT ACCEPTED", "ssh_auth", "watchtower attest gway-002 --dry-run",
            "Stage B is currently", "not an automated apply",
            "gway-exec", "arthe", "remote_managed_repositories: []",
            "durable", "StrictHostKeyChecking=no",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
