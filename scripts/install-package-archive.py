#!/usr/bin/env python3
"""Install the committed GWay Remote Python package using one Git archive.

Executed locally as root by Ansible. Never fetches from the network. Each
content-addressed release is verified before a single symlink pointer switch.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import tempfile


PACKAGE = "gway_remote"
RELEASES = ".package-releases"
LEGACY = ".gway_remote.legacy-before-archive"


def _archive(source: Path) -> bytes:
    # A committed tree is authoritative; Python caches and ignored files do
    # not enter the package. No dependency on an external tar implementation.
    return subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", "HEAD:gway_remote"],
        check=True, capture_output=True, timeout=30,
    ).stdout


def _validate_root(root: Path):
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("installation root must be an absolute real directory")
    if not root.is_dir():
        raise ValueError("installation root missing")
    info = root.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("installation root must be root-owned, not writable by other users")


def _unpack(archive: bytes, package_dir: Path):
    paths = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or not path.parts or
                    any(part in ("", ".", "..") for part in path.parts)):
                raise ValueError("unsafe archive path")
            # Git tree for the package is the tar root. Exclude unusual
            # entries (symlinks, device files, hardlinks) rather than following.
            dest = package_dir.joinpath(*path.parts)
            if member.isdir():
                dest.mkdir(mode=0o755, parents=True, exist_ok=True)
                continue
            if not member.isfile() or member.name in paths:
                raise ValueError("unsafe archive member")
            paths.add(member.name)
            dest.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError("archive file missing payload")
            with dest.open("xb") as output:
                while chunk := source.read(65536):
                    output.write(chunk)
            dest.chmod(0o644)

    for required in ("__init__.py", "__main__.py", "node_exec_worker.py"):
        if required not in paths:
            raise ValueError("incomplete GWay package: " + required)
    # Fail before switching the live path if packaging introduced broken syntax.
    for name in paths:
        if name.endswith(".py"):
            ast.parse((package_dir / name).read_text(encoding="utf-8"), filename=name)


def install(source: Path, root: Path, *, before_activate=None):
    _validate_root(root)
    archive = _archive(source)
    digest = hashlib.sha256(archive).hexdigest()
    releases = root / RELEASES
    if releases.is_symlink():
        raise ValueError("release directory must not be a symlink")
    releases.mkdir(mode=0o755, exist_ok=True)
    if releases.stat().st_uid != 0 or releases.stat().st_mode & 0o022:
        raise PermissionError("unsafe release directory")

    relative = f"{RELEASES}/{digest}/{PACKAGE}"
    current = root / PACKAGE
    if current.is_symlink() and os.readlink(current) == relative:
        if not (root / relative / "__main__.py").is_file():
            raise ValueError("live release is missing its package")
        return {"changed": False, "sha256": digest}

    if current.is_symlink() and not os.readlink(current).startswith(RELEASES + "/"):
        raise ValueError("unmanaged package symlink")
    if current.exists() and not (current.is_dir() or current.is_symlink()):
        raise ValueError("unsafe existing package")
    target = releases / digest
    if target.is_symlink():
        raise ValueError("release target is a symlink")
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=releases) as temp:
            stage = Path(temp)
            package_dir = stage / PACKAGE
            package_dir.mkdir(mode=0o755)
            _unpack(archive, package_dir)
            # Staging completes before the version becomes visible.
            os.rename(stage, target)
    if not (target / PACKAGE / "__main__.py").is_file():
        raise ValueError("existing release is incomplete")

    if before_activate is not None:
        before_activate()  # test seam: no live path may change on a stage failure

    pending = root / ".gway_remote.next"
    if pending.exists() or pending.is_symlink():
        raise ValueError("stale pending symlink; refusing to overwrite")
    pending.symlink_to(relative)
    legacy = root / LEGACY
    moved_legacy = False
    try:
        if current.exists() and not current.is_symlink():
            if legacy.exists() or legacy.is_symlink():
                raise ValueError("legacy package backup already exists")
            current.rename(legacy)
            moved_legacy = True
        os.replace(pending, current)  # atomic on all symlink-based deployments
    except Exception:
        pending.unlink(missing_ok=True)
        if moved_legacy:
            legacy.rename(current)
        raise

    return {"changed": True, "sha256": digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("root is required for package installation")
    print(json.dumps(install(args.source, args.root), sort_keys=True))


if __name__ == "__main__":
    main()
