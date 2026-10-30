"""Read-only release retention inventory; deliberately does not authorize deletion.

Issue #306 phase A.  Potential candidates are *not* a deletion plan: runtime,
rollback and shared-dependency ownership require per-owner proof first.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat

from .reconcile import TARGETS

# Fixed owner-defined installation conventions. Never discover roots by searching
# a home directory, and never accept a path from the command line.
ROOTS = {
    "ocpp-csms": ("home", ".local/share/ocpp-csms"),
    "ocpp-reports": ("absolute", "/opt/ocpp-reports"),
    "ocpp-simulator": ("home", ".local/share/ocpp-simulator"),
    "gway-lcd-sound": ("home", ".local/share/gway-lcd-sound"),
    "gway-agent-ops": ("home", ".local/share/gway-agent-ops"),
    "gway-rfid": ("home", ".local/share/gway-rfid"),
    "gway-bastion": ("absolute", "/opt/gway-bastion"),
}
# Kiosk's current installation format is not a registered immutable release root.
# Excluding it is preferable to guessing /var/lib/ or /opt/ paths.
EXECUTABLE_LINKS = {
    "ocpp-csms": (),
    "ocpp-reports": ("/usr/local/bin/ocpp-reports",),
    "ocpp-simulator": (".local/bin/ocpp-simulator",),
    "gway-lcd-sound": (".local/bin/gway-app-observer",),
    "gway-agent-ops": (".local/bin/agent",),
    "gway-rfid": (),
}


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _tree_size(path: Path, *, limit: int = 50000) -> tuple[int | None, str | None]:
    """Count regular-file allocated bytes without following directory symlinks."""
    total = 0
    visited = 0
    try:
        for base, dirs, files in os.walk(path, topdown=True, followlinks=False):
            for name in list(dirs):
                item = Path(base) / name
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode):
                    dirs.remove(name)
                elif not stat.S_ISDIR(info.st_mode):
                    return None, "non-directory entry"
            for name in files:
                info = (Path(base) / name).lstat()
                if stat.S_ISLNK(info.st_mode):
                    continue
                if not stat.S_ISREG(info.st_mode):
                    return None, "special file in release"
                total += info.st_blocks * 512
                visited += 1
                if visited > limit:
                    return None, "file count limit exceeded"
    except (OSError, RuntimeError) as exc:
        return None, type(exc).__name__
    return total, None


def preview(repository=None, *, home=None, roots=None):
    """Inspect only registered roots; no subprocess, writes, or network access."""
    names = tuple(name for name, _ in TARGETS)
    if repository is not None and repository not in names:
        raise ValueError("unregistered target")
    home = Path(home) if home is not None else Path.home()
    specs = ROOTS if roots is None else roots  # test-only injectable root mapping
    rows = []
    for name in names:
        if repository is not None and name != repository:
            continue
        if name not in specs:
            rows.append({"name": name, "status": "unsupported",
                         "reason": "no approved immutable release root",
                         "releases": [], "potential_bytes": 0})
            continue
        kind, location = specs[name]
        if kind not in ("home", "absolute"):
            raise ValueError("invalid root kind")
        root = home / location if kind == "home" else Path(location)
        if not root.is_absolute() or root == Path("/") or (kind == "home" and
                (Path(location).is_absolute() or ".." in Path(location).parts)):
            raise ValueError("unsafe release root")
        entry = {"name": name, "root": str(root), "status": "blocked",
                 "reason": "owner runtime, rollback and dependency references not fully verified",
                 "releases": [], "potential_bytes": 0,
                 "protected": [], "errors": []}
        rows.append(entry)
        try:
            if root.is_symlink():
                entry["errors"].append("installation root is a symlink")
                continue
            if not root.exists():
                entry["status"] = "absent"
                entry["reason"] = "installation root not found"
                continue
            if not root.is_dir():
                entry["errors"].append("installation root is not a directory")
                continue
            directory = root / "releases"
            if directory.is_symlink():
                entry["errors"].append("releases directory is a symlink")
                continue
            if not directory.is_dir():
                entry["errors"].append("releases directory unavailable")
                continue
            protected = set()
            for link in (root / "current", root / "previous"):
                if link.is_symlink():
                    resolved = link.resolve(strict=True)
                    if not _within(resolved, directory.resolve(strict=True)):
                        entry["errors"].append("release link escapes root: " + str(link))
                        continue
                    protected.add(resolved)
                    entry["protected"].append({"link": str(link), "target": str(resolved)})
                elif link.exists():
                    entry["errors"].append("unexpected non-link activation path: " + str(link))
            for executable in EXECUTABLE_LINKS.get(name, ()):
                link = home / executable if not executable.startswith("/") else Path(executable)
                if link.is_symlink():
                    resolved = link.resolve(strict=True)
                    if not _within(resolved, directory.resolve(strict=True)):
                        entry["errors"].append("executable link outside release root: " + str(link))
                        continue
                    ancestor = next((p for p in (resolved, *resolved.parents)
                                     if p.parent == directory.resolve(strict=True)), None)
                    if ancestor:
                        protected.add(ancestor)
                        entry["protected"].append({"link": str(link), "target": str(ancestor)})
                elif link.exists():
                    entry["errors"].append("unexpected non-link executable: " + str(link))
            for release in sorted(directory.iterdir(), key=lambda p: p.name):
                if release.is_symlink():
                    entry["errors"].append("symlink release skipped: " + release.name)
                    continue
                if not release.is_dir():
                    entry["errors"].append("non-directory release skipped: " + release.name)
                    continue
                allocated, error = _tree_size(release)
                if error:
                    entry["errors"].append(release.name + ": " + error)
                role = "referenced" if release in protected else "unverified"
                entry["releases"].append({"path": str(release), "classification": role,
                                          "allocated_bytes": allocated, "deletable": False,
                                          "reason": ("activation reference" if role == "referenced"
                                                     else "owner/runtime/rollback proof missing")})
                if role == "unverified" and allocated is not None:
                    entry["potential_bytes"] += allocated
        except (OSError, RuntimeError) as exc:
            entry["errors"].append(type(exc).__name__ + ": " + str(exc))
        if entry["errors"]:
            entry["reason"] = "incomplete or unsafe inventory; no deletion authorized"
    return {"schema": "gway-remote/retention-preview/v1", "dry_run": True,
            "deletion_enabled": False, "targets": rows}


def format_preview(report):
    lines = ["Retention preview (read-only; no deletion is authorized)"]
    for row in report["targets"]:
        lines.append(f'{row["name"]}: {row["status"]} — {row["reason"]}')
        if row.get("root"):
            lines.append("  root: " + row["root"])
        for item in row["releases"]:
            lines.append(f'  {item["classification"]}: {item["path"]} '
                         f'({item["allocated_bytes"] if item["allocated_bytes"] is not None else "unknown"} allocated bytes; NOT deletable)')
        for error in row.get("errors", []):
            lines.append("  warning: " + error)
    lines.append("Potential bytes are informational only, not safe reclaimable-space estimates.")
    return "\n".join(lines)
