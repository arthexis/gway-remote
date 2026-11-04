#!/usr/bin/env python3
"""Stage an exact Git revision as an isolated MCP runtime; never activate it."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

LAUNCHER = '''import importlib
from pathlib import Path
import runpy
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
modules = ("mcp_http", "mcp_bearer_gateway", "mcp_link_http")
command = sys.argv.pop(1) if len(sys.argv) > 1 else ""
if command == "--check":
    for name in modules:
        importlib.import_module("gway_remote." + name)
    print("MCP runtime imports OK")
elif command in modules:
    runpy.run_module("gway_remote." + command, run_name="__main__")
elif command == "node_inventory":
    runpy.run_module("gway_remote.node_registry_inventory", run_name="__main__")
elif command == "exec_eligibility":
    runpy.run_module("gway_remote.watchtower_exec_eligibility", run_name="__main__")
elif command == "bearer":
    sys.argv.insert(1, "bearer")
    runpy.run_module("gway_remote.__main__", run_name="__main__")
else:
    raise SystemExit("Expected --check, bearer or an MCP service module")
'''


def stage(source, revision, prefix):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("An exact 40-character reviewed commit SHA is required")
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "--verify", revision + "^{commit}"], text=True
    ).strip()
    if actual != revision:
        raise ValueError("Revision is not the exact commit")
    archive = subprocess.check_output(
        ["git", "-C", str(source), "archive", revision, "gway_remote", "deploy/mcp-bearer"]
    )
    prefix = Path(prefix)
    releases = prefix / "releases"
    for directory in (prefix.absolute(), *prefix.absolute().parents, releases):
        if directory.is_symlink():
            raise ValueError("Runtime roots and ancestors must not be symlinks")
    for directory in (prefix, releases):
        if directory.exists() and (not directory.is_dir()
                or directory.stat().st_uid != os.geteuid()
                or directory.stat().st_mode & 0o022):
            raise ValueError("Existing runtime roots must be owned by the installer and not group/world writable")
    releases.mkdir(parents=True, exist_ok=True, mode=0o755)
    prefix.chmod(0o755)
    releases.chmod(0o755)
    release = releases / revision
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=releases) as temp:
        candidate = Path(temp) / "runtime"
        candidate.mkdir(mode=0o755)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar:
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Unsafe archive path")
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("Runtime archive must contain regular files only")
                target = candidate / path
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                for directory in target.parents:
                    directory.chmod(0o755)
                    if directory == candidate:
                        break
                target.write_bytes(tar.extractfile(member).read())
                target.chmod(0o644)
        (candidate / "run.py").write_text(LAUNCHER)
        (candidate / "run.py").chmod(0o644)
        manifest = {"revision": revision, "sha256": {
            str(path.relative_to(candidate)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(candidate.rglob("*")) if path.is_file()
        }}
        (candidate / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
        (candidate / "manifest.json").chmod(0o644)
        subprocess.run(["/usr/bin/python3", "-I", str(candidate / "run.py"), "--check"], check=True)
        if release.is_symlink():
            raise ValueError("Existing release must not be a symlink")
        if release.exists():
            expected = {str(p.relative_to(candidate)): p.read_bytes()
                        for p in candidate.rglob("*") if p.is_file()}
            observed = {str(p.relative_to(release)): p.read_bytes()
                        for p in release.rglob("*") if p.is_file()}
            paths = [release, *release.rglob("*")]
            unsafe = any(p.is_symlink() or p.stat().st_uid != os.geteuid()
                         or (p.stat().st_mode & 0o777) != (0o755 if p.is_dir() else 0o644)
                         for p in paths)
            if expected != observed or unsafe:
                raise ValueError("Existing immutable release differs; refusing replacement")
        else:
            candidate.rename(release)
    # Keep the previous release for an explicit operator rollback. No service action.
    current = prefix / "current"
    if current.is_symlink() and os.readlink(current) != str(Path("releases") / revision):
        previous = prefix / ".previous-new"
        previous.unlink(missing_ok=True)
        previous.symlink_to(os.readlink(current))
        previous.replace(prefix / "previous")
    pending = prefix / ".current-new"
    pending.unlink(missing_ok=True)
    pending.symlink_to(Path("releases") / revision)
    pending.replace(current)
    print("STAGED MCP revision " + revision + "; no services started or enabled")
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--prefix", type=Path, default=Path("/opt/gway-mcp"))
    args = parser.parse_args()
    stage(args.source, args.revision, args.prefix)


if __name__ == "__main__":
    main()
