"""Validate effective SSH trust without accepting keys or changing configuration."""
import os
import subprocess
from pathlib import Path


def _trusted_parent_directories(path):
    parent = path.parent
    while parent != parent.parent:
        info = parent.stat()
        if parent.is_symlink() or info.st_mode & 0o022:
            raise ValueError("unsafe SSH trust directory")
        parent = parent.parent


def trusted_file(path, *, secret=False):
    path = Path(path).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("SSH trust file unavailable")
    info = path.stat()
    if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
        raise ValueError("unsafe SSH trust file permissions")
    if secret and info.st_mode & 0o077:
        raise ValueError("unsafe SSH private key permissions")
    _trusted_parent_directories(path)


def trusted_agent_socket(path):
    """Accept only a protected, local SSH-agent socket owned by the caller."""
    path = Path(path).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_socket():
        raise ValueError("SSH agent socket unavailable")
    info = path.stat()
    if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o077:
        raise ValueError("unsafe SSH agent socket permissions")
    _trusted_parent_directories(path)


def validate_profile(config, alias, *, hostname, require_jump=False, runner=subprocess.run):
    trusted_file(config)
    try:
        result = runner(["ssh", "-F", str(config), "-G", alias],
                        capture_output=True, text=True, check=True, timeout=8)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError("SSH profile unavailable") from exc
    options = dict(line.split(None, 1) for line in result.stdout.splitlines() if " " in line)
    if (options.get("hostname") != hostname
            or options.get("batchmode", "").lower() != "yes"
            or options.get("stricthostkeychecking", "").lower() != "yes"
            or options.get("identitiesonly", "").lower() != "yes"):
        raise ValueError("SSH profile identity/trust mismatch")
    if not options.get("user") or options["user"] in ("root", "none"):
        raise ValueError("SSH inspection user unavailable")
    jump = options.get("proxyjump", "none")
    if require_jump and jump in ("none", ""):
        raise ValueError("SSH Bastion jump missing")
    known = options.get("userknownhostsfile", "").split()
    if not known or any(p.lower() in ("/dev/null", "none") for p in known):
        raise ValueError("SSH pinned known-hosts unavailable")
    for path in known:
        trusted_file(path)
    identities = [path for path in options.get("identityfile", "").split()
                  if path.lower() != "none"]
    agent = options.get("identityagent", "none")
    if agent.lower() not in ("", "none"):
        trusted_agent_socket(agent)
        if not identities:
            raise ValueError("SSH agent public identity unavailable")
        for path in identities:
            # This is the public half used to select a Bastion-held private key.
            if not path.endswith(".pub"):
                raise ValueError("SSH agent identity must be public")
            trusted_file(path)
        return options
    if not identities:
        raise ValueError("SSH identity unavailable")
    for path in identities:
        trusted_file(path, secret=True)
    return options
