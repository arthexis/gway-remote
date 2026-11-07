#!/usr/bin/env python3
"""One-time migration of already-installed providers to manifest discovery.

Called as root by the existing reviewed Ansible deployment. No approval step.
"""
import json
import os
from pathlib import Path
import re
import tempfile

DEST = Path("/etc/gway-mcp-providers")
LEGACY = Path("/etc/gway-mcp-gateway/sources.json")
AGENT_CURRENT = Path("/home/arthe/.local/share/gway-agent-ops/current")


def publish(item):
    name = item["source_id"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", name):
        raise ValueError("invalid provider name")
    manifest = {key: item[key] for key in ("source_id", "revision", "executable", "argv")}
    path = DEST / (name + ".json")
    fd, temp = tempfile.mkstemp(prefix=".provider-", dir=DEST)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(manifest, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    if os.geteuid() != 0:
        raise ValueError("root-owned manifest publication required")
    DEST.mkdir(mode=0o755, exist_ok=True)
    stat = DEST.lstat()
    if DEST.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise ValueError("untrusted manifest directory")
    if LEGACY.exists():
        data = json.loads(LEGACY.read_text())
        for source in data["sources"]:
            registration = source["registration"]
            if registration["enabled"]:
                publish(registration)
    if AGENT_CURRENT.is_symlink():
        release = AGENT_CURRENT.resolve(strict=True)
        if not re.fullmatch(r"[a-f0-9]{40}", release.name):
            raise ValueError("invalid AgentOps release")
        executable = release / "bin/agent-mcp"
        if executable.is_file() and executable.stat().st_mode & 0o111:
            publish({"source_id": "agentops", "revision": release.name,
                     "executable": str(executable), "argv": [str(executable)]})


if __name__ == "__main__":
    main()
