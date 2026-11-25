"""Run the actual Ansible transaction on disposable files, never systemd."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLAY = ROOT / "ansible/playbooks/watchtower-mcp-node-routing.yml"
SHA = "a" * 40
PREFIX = "[Service]\nEnvironment=GWAY_MCP_NODE_ROUTING="


class RoutingActivationTests(unittest.TestCase):
    def exercise(self, case):
        if not shutil.which("ansible-playbook"):
            self.skipTest("ansible-core unavailable")
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML unavailable")
        with tempfile.TemporaryDirectory(prefix="routing-716-") as d:
            root = Path(d)
            dropin = root / "80-node-routing.conf"
            other = root / "70-other.conf"
            other.write_text("unrelated\n")
            active = root / "running"
            active.write_text("legacy")
            restarts = root / "restarts"
            fault = root / "fault"
            helper = root / "fake.py"
            helper.write_text("""import sys
from pathlib import Path
r=Path(__file__).parent
p=r/'80-node-routing.conf'
a=r/'running'
if sys.argv[1]=='restart':
    with (r/'restarts').open('a') as log: log.write('restart\\n')
    a.write_text(p.read_text().strip().split('=')[-1] if p.exists() else 'legacy')
    if (r/'fault').exists() and (r/'fault').read_text()=='restart':
        (r/'fault').unlink()
        sys.exit(1)
else:
    mode=a.read_text()
    if len(sys.argv)>2 and (mode!=sys.argv[2] or ((r/'fault').exists() and
        (r/'fault').read_text()==mode)): sys.exit(1)
    print(mode)
""")
            source = yaml.safe_load(PLAY.read_text())
            play = source[0]
            play["become"] = False
            def rewrite(tasks):
                for t in tasks:
                    name = t["name"]
                    for key in ("block", "rescue"):
                        if key in t:
                            rewrite(t[key])
                    for module in ("stat", "slurp", "file", "copy"):
                        args = t.get("ansible.builtin." + module)
                        if args:
                            for key in ("path", "src", "dest"):
                                if key in args:
                                    args[key] = str(dropin if args[key].endswith(".conf") else root)
                            args.pop("owner", None)
                            args.pop("group", None)
                    if "ansible.builtin.assert" in t:
                        t["ansible.builtin.assert"]["that"] = [
                            s.replace("uid == 0", f"uid == {os.getuid()}")
                             .replace("gid == 0", f"gid == {os.getgid()}")
                            for s in t["ansible.builtin.assert"]["that"]]
                    if name == "Verify installed release pointer":
                        t["ansible.builtin.command"]["argv"] = ["/usr/bin/printf", "releases/" + SHA]
                    if name == "Verify installed gateway supports routing mode":
                        t["ansible.builtin.command"]["argv"] = ["/usr/bin/true"]
                    if "ansible.builtin.systemd" in t:
                        self.assertEqual(t.pop("ansible.builtin.systemd")["name"],
                                         "gway-mcp-gateway.service")
                        t["ansible.builtin.command"] = {
                            "argv": ["/usr/bin/python3", str(helper), "restart"]}
                    args = t.get("ansible.builtin.command", {}).get("argv", [])
                    if any("watchtower-routing-probe.py" in arg for arg in args):
                        t["ansible.builtin.command"]["argv"] = [
                            "/usr/bin/python3", str(helper), "probe", *args[2:]]
                        if "retries" in t:
                            t.update(retries=1, delay=0)
            rewrite(play["tasks"])
            fixture = root / "play.yml"
            fixture.write_text(yaml.safe_dump(source, sort_keys=False))

            def run(mode, success=True, revision=SHA):
                result = subprocess.run(
                    ["ansible-playbook", "-i", "localhost,", str(fixture),
                     "-e", "mcp_routing_revision=" + revision,
                     "-e", "mcp_routing_mode=" + mode],
                    capture_output=True, text=True, timeout=90,
                    env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(root / "tmp"), "ANSIBLE_PIPELINING": "True"})
                self.assertEqual(result.returncode == 0, success,
                                 result.stdout + result.stderr)
                self.assertEqual(other.read_text(), "unrelated\n")
                return result.stdout

            def count():
                return len(restarts.read_text().splitlines()) if restarts.exists() else 0

            if case == "default":
                run("legacy")
                self.assertFalse(dropin.exists())
                self.assertEqual(count(), 0)
            elif case == "activate":
                run("canonical-with-aliases")
                self.assertEqual(dropin.read_text(), PREFIX + "canonical-with-aliases\n")
                self.assertEqual(active.read_text(), "canonical-with-aliases")
                self.assertEqual(count(), 1)
            elif case in ("noop", "rollback_present", "canonical", "legacy"):
                dropin.write_text(PREFIX + "canonical-with-aliases\n")
                dropin.chmod(0o644)
                active.write_text("canonical-with-aliases")
                if case == "rollback_present":
                    fault.write_text("restart")
                    self.assertIn("previous drop-in and running mode restored",
                                  run("canonical", False))
                    self.assertEqual(count(), 2)
                    expected = "canonical-with-aliases"
                elif case == "noop":
                    run("canonical-with-aliases")
                    self.assertEqual(count(), 0)
                    expected = "canonical-with-aliases"
                else:
                    run(case)
                    self.assertEqual(count(), 1)
                    expected = case
                self.assertEqual(dropin.read_text(), PREFIX + expected + "\n")
                self.assertEqual(active.read_text(), expected)
            elif case == "rollback_absent":
                fault.write_text("canonical-with-aliases")
                self.assertIn("previous drop-in and running mode restored",
                              run("canonical-with-aliases", False))
                self.assertFalse(dropin.exists())
                self.assertEqual(active.read_text(), "legacy")
                self.assertEqual(count(), 2)
            elif case == "reject":
                run("invalid", False)
                run("canonical", False, "b" * 40)
                dropin.write_text("unmanaged\n")
                dropin.chmod(0o644)
                run("canonical", False)
                self.assertEqual(dropin.read_text(), "unmanaged\n")
                self.assertEqual(count(), 0)
            else:
                self.fail("unknown case")

    def test_default(self):
        self.exercise("default")

    def test_activation(self):
        self.exercise("activate")

    def test_noop(self):
        self.exercise("noop")

    def test_canonical(self):
        self.exercise("canonical")

    def test_return_legacy(self):
        self.exercise("legacy")

    def test_rollback_absent(self):
        self.exercise("rollback_absent")

    def test_rollback_present(self):
        self.exercise("rollback_present")

    def test_reject_invalid(self):
        self.exercise("reject")


if __name__ == "__main__":
    unittest.main()
