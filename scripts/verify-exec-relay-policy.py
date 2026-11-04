#!/usr/bin/env python3
"""Read-only attestation of the fixed, existing MCP relay identity.

Used before and after a selected-executor cutover. This does not modify SSH,
sudoers, secrets, authorization or running jobs.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import stat

SSHD_CONFIG = Path("/etc/ssh/sshd_config.d/40-gway-exec-relay.conf")
SUDOERS_CONFIG = Path("/etc/sudoers.d/gway-exec-relay")
PROTOCOL = "/usr/bin/env PYTHONPATH=/opt/gway-remote /usr/bin/python3 -m gway_remote.node_exec_protocol"
FORCE = re.compile(r"\s*ForceCommand /usr/bin/sudo -n -u (gway-exec|arthe) (.*)")
ALLOW = re.compile(r"gway-relay ALL=\((gway-exec|arthe)\) NOPASSWD: (.*)")


def _protected_regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("unsafe relay policy file")
    return path.read_text(encoding="utf-8")


def verify(sshd, sudoers, expected_user=None):
    """Match the exact protocol and identical identity in both policy files."""
    ssh_matches = [match for line in sshd.splitlines()
                   if (match := FORCE.fullmatch(line)) is not None]
    sudo_matches = [match for line in sudoers.splitlines()
                    if (match := ALLOW.fullmatch(line)) is not None]
    if len(ssh_matches) != 1 or len(sudo_matches) != 1:
        raise ValueError("relay protocol must be unique")
    ssh_user, ssh_command = ssh_matches[0].groups()
    sudo_user, sudo_command = sudo_matches[0].groups()
    if (ssh_user != sudo_user or ssh_command != PROTOCOL
            or sudo_command != PROTOCOL):
        raise ValueError("relay identity or protocol mismatch")
    if expected_user is not None and ssh_user != expected_user:
        raise ValueError("relay identity does not match selected user")
    # No extra allow rule for this principal in this dedicated file.
    active = [line.strip() for line in sudoers.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    if len(active) != 1 or active[0] != sudo_matches[0].group(0):
        raise ValueError("relay sudoers contains additional privileges")
    return ssh_user


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", choices=("gway-exec", "arthe"))
    args = parser.parse_args()
    try:
        ssh = _protected_regular(SSHD_CONFIG)
        sudo = _protected_regular(SUDOERS_CONFIG)
        user = verify(ssh, sudo, args.user)
    except (OSError, UnicodeError, ValueError, PermissionError) as exc:
        raise SystemExit("relay identity verification failed") from None
    print("relay identity verified:", user)


if __name__ == "__main__":
    main()
