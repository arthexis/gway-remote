#!/usr/bin/python3
"""Fixed SSH authorized_keys entrypoint; never interpret a caller command."""
import os
import pwd
import sys

def main():
    # The SSH command is a protocol marker, not a shell command.
    if os.environ.get("SSH_ORIGINAL_COMMAND") != "gway-exec-protocol-v1":
        return 1
    if os.geteuid() == 0 or os.getuid() != os.geteuid():
        return 1
    if os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION") is None:
        return 1
    account = pwd.getpwuid(os.geteuid())
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "LANG": "C.UTF-8",
        "PYTHONPATH": "/opt/gway-remote",
    }
    os.execve("/usr/bin/python3",
              ["/usr/bin/python3", "-m", "gway_remote.node_exec_protocol"], env)

if __name__ == "__main__":
    sys.exit(main())
