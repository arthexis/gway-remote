"""Exercise the production Ansible cutover block/rescue on disposable files (#533)."""
import base64
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SELECT = ROOT / "ansible/roles/gway_remote/tasks/node-exec-select.yml"


class IsolatedCutoverTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-core unavailable")
    def test_failure_compensation(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is installed only in the isolated Ansible CI job")
        source = yaml.safe_load(SELECT.read_text())
        blocks = [t for t in source if t.get("name") == "Activate selected execution identity and update only existing relay"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(len(blocks[0]["block"]), 8)
        self.assertEqual(len(blocks[0]["rescue"]), 10)
        for fault in ("Validate full sshd configuration", "Reload SSH with", "Verify selected executor can import"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory(prefix="gway533-", dir="/tmp") as tmp:
                root = Path(tmp)
                names = ("executor-identity.json", "gway-exec-relay", "40-gway-exec-relay.conf", "gway-mcp-file-reader")
                originals = (
                    b'{"user":"original_user"}\n',
                    b'gway-relay ALL=(original_user) NOPASSWD: /usr/bin/true\n',
                    b'ForceCommand sudo -n -u original_user /usr/bin/env PYTHONPATH=/opt/gway-remote python3 -m worker\n',
                    b'arthe ALL=(gway-exec) NOPASSWD: /usr/bin/true\n',
                )
                for name, data in zip(names, originals):
                    (root / name).write_bytes(data)
                cutover = copy.deepcopy(blocks[0])
                injected = 0
                for section in ("block", "rescue"):
                    for task in cutover[section]:
                        name = task["name"]
                        if "ansible.builtin.copy" in task:
                            args = task["ansible.builtin.copy"]
                            args["dest"] = str(root / Path(args["dest"]).name)
                            for key in ("owner", "group", "validate"):
                                args.pop(key, None)
                        elif "ansible.builtin.file" in task:
                            args = task["ansible.builtin.file"]
                            args["path"] = str(root / Path(args["path"]).name)
                        elif section == "rescue" and name.startswith("Restore ") and "ansible.builtin.command" in task:
                            args = task["ansible.builtin.command"]["argv"]
                            args[-4] = str(root / Path(args[-4]).name)
                            if args[-1] == "/usr/sbin/visudo":
                                args[-1] = "/usr/bin/true"
                        elif "ansible.builtin.command" in task or "ansible.builtin.systemd" in task:
                            fail = section == "block" and fault in name
                            injected += int(fail)
                            task.pop("ansible.builtin.command", None)
                            task.pop("ansible.builtin.systemd", None)
                            task["ansible.builtin.command"] = {"argv": ["/usr/bin/false" if fail else "/usr/bin/true"]}
                            task["changed_when"] = False
                self.assertEqual(injected, 1)
                self.assertIn("ansible.builtin.fail", cutover["rescue"][-1])
                present = {"stat": {"exists": True}}
                variables = {
                    "gway_remote_exec_run_user": "arthe",
                    "ansible_hostname": "gway-001",
                    "exec_file_reader_old": present,
                    "exec_file_reader_original": {"content": base64.b64encode(originals[3]).decode()},
                    "gway_remote_install_root": "/opt/gway-remote",
                    "exec_relay_files": {"results": [present, present]},
                    "exec_identity_old": present,
                    "exec_identity_original": {"content": base64.b64encode(originals[0]).decode()},
                    "exec_relay_sudo_original": {"content": base64.b64encode(originals[1]).decode()},
                    "exec_relay_sshd_original": {"content": base64.b64encode(originals[2]).decode()},
                }
                playbook = root / "cutover.yml"
                playbook.write_text(yaml.safe_dump([{
                    "hosts": "localhost", "connection": "local", "gather_facts": False,
                    "vars": variables, "tasks": [cutover],
                }], sort_keys=False))
                result = subprocess.run(
                    ["ansible-playbook", "-i", "localhost,", str(playbook)],
                    capture_output=True, text=True, timeout=90,
                    env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(root / "ansible-tmp")},
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Restore previous isolated file reader policy", result.stdout)
                self.assertIn("Refuse partially switched executor identity", result.stdout)
                self.assertIn("Executor identity change failed", result.stdout)
                for name, original in zip(names, originals):
                    self.assertEqual((root / name).read_bytes(), original, name + result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
