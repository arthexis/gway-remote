#!/usr/bin/env python3
"""Validate the actual Ansible SSH relay fragment against this host's OpenSSH.

Runs in disposable Debian CI containers with their real sshd, no services started.
The baseline models the global policy and includes the exact Ansible copy content.
"""
from __future__ import annotations

import pathlib
import subprocess
import tempfile
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/gway_remote/tasks/node-exec-relay.yml"
TASK = "Install dedicated SSHD Match block with forced protocol only"
FORCE_COMMAND = (
    "/usr/bin/sudo -n -u gway-exec /usr/bin/env "
    "PYTHONPATH=/opt/gway-remote /usr/bin/python3 "
    "-m gway_remote.node_exec_protocol"
)
EXPECTED = {
    "authenticationmethods": "publickey",
    "passwordauthentication": "no",
    "kbdinteractiveauthentication": "no",
    "permittty": "no",
    "disableforwarding": "yes",
    "allowagentforwarding": "no",
    "allowtcpforwarding": "no",
    "x11forwarding": "no",
    "permittunnel": "no",
    "permituserenvironment": "no",
    "authorizedkeysfile": "/var/lib/gway-relay/.ssh/authorized_keys",
    "forcecommand": FORCE_COMMAND,
}


def run(*argv: str) -> str:
    outcome = subprocess.run(argv, check=True, text=True, capture_output=True)
    return outcome.stdout


def fragment() -> str:
    data = yaml.safe_load(ROLE.read_text(encoding="utf-8"))
    entries = [task["ansible.builtin.copy"]["content"]
               for task in data if task.get("name") == TASK]
    if len(entries) != 1 or not entries[0].startswith("Match User gway-relay\n"):
        raise AssertionError("exactly one expected relay Match block required")
    if "{{" in entries[0] or "{%" in entries[0]:
        raise AssertionError("unrendered Ansible template in sshd configuration")
    return entries[0]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gway-relay-sshd-") as directory:
        root = pathlib.Path(directory)
        hostkey = root / "host_ed25519"
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(hostkey))
        snippet = root / "40-gway-exec-relay.conf"
        snippet.write_text(fragment(), encoding="utf-8")
        config = root / "sshd_config"
        config.write_text(
            "Port 2222\n"
            f"HostKey {hostkey}\n"
            "PermitUserEnvironment no\n"
            f"Include {snippet}\n",
            encoding="utf-8",
        )
        pathlib.Path("/run/sshd").mkdir(parents=True, exist_ok=True)
        # Syntax is checked on the assembled config, not a manually copied policy.
        run("/usr/sbin/sshd", "-t", "-f", str(config))
        output = run(
            "/usr/sbin/sshd", "-T", "-f", str(config),
            "-C", "user=gway-relay,host=gway-001,addr=10.90.0.1",
        )
        actual = dict(line.split(" ", 1) for line in output.splitlines() if " " in line)
        for key, expected in EXPECTED.items():
            observed = actual.get(key)
            if observed != expected:
                raise AssertionError(f"{key}: expected {expected!r}, got {observed!r}")

        # Unrelated users must not inherit the relay's forced command.
        other = run(
            "/usr/sbin/sshd", "-T", "-f", str(config),
            "-C", "user=ordinary,host=gway-001,addr=10.90.0.1",
        )
        other_settings = dict(line.split(" ", 1) for line in other.splitlines() if " " in line)
        if other_settings.get("forcecommand") != "none":
            raise AssertionError("relay ForceCommand escaped its Match block")
        print("PASS: real OpenSSH syntax, relay effective policy and user isolation")


if __name__ == "__main__":
    main()
