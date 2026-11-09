#!/usr/bin/env python3
"""Fixed, non-root Odoo repository-owned installer adapter (not provisioned).

Only an operator-controlled checkout path may be supplied through a protected
installation configuration, never through the SSH request.
"""
import os
from pathlib import Path
import re
import subprocess
import sys

REPO = Path("/opt/odoo-gelectriic/source")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def run_fixed_deploy(sha, *, source=REPO, run=subprocess.run):
    if os.geteuid() == 0:
        raise PermissionError("Odoo deploy.sh refuses root; run as fixed operator")
    if type(sha) is not str or not SHA.fullmatch(sha):
        raise ValueError("immutable SHA required")
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise PermissionError("missing trusted checkout")
    def git(*args):
        return run(["/usr/bin/git", "-C", str(source), *args], check=True,
                   capture_output=True, text=True, timeout=15).stdout.strip()
    if (git("rev-parse", "--verify", "HEAD") != sha or
            git("branch", "--show-current") != "main" or
            git("status", "--porcelain")):
        raise PermissionError("checkout SHA, branch or cleanliness mismatch")
    script = source / "deploy.sh"
    if script.is_symlink() or not script.is_file():
        raise PermissionError("missing repository-owned deploy.sh")
    run(["/bin/sh", str(script)], cwd=source, check=True, timeout=900,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin",
             "HOME": str(Path.home())})
    # The repo's own integrity check verifies active release artifacts.
    run(["/usr/bin/python3", str(source / "scripts/deploy-cli.py"),
         "is-installed", "--revision", sha], cwd=source, check=True,
        timeout=30, env={"PATH": "/usr/local/bin:/usr/bin:/bin",
                         "HOME": str(Path.home())})
    return {"sha": sha, "status": "verified"}


def main():
    if len(sys.argv) != 2:
        return 2
    try:
        run_fixed_deploy(sys.argv[1])
    except (OSError, ValueError, PermissionError, subprocess.SubprocessError):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
