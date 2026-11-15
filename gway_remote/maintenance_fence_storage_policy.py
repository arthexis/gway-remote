"""Offline fd-anchored SQLite file ownership audit, NOT an SQLite opener.

No sqlite3.connect, filesystem mutation, permission fixing or admission.
Returning a report does not remove a later connect(path) TOCTOU window.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat


class StoragePolicyError(ValueError):
    def __init__(self):
        super().__init__("invalid_maintenance_storage_v1c2")


@dataclass(frozen=True)
class StorageReport:
    checked_files: tuple[str, ...]
    uid: int


def _mode_secure(info, uid, *, directory=False, ancestor=False):
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise StoragePolicyError()
        if ancestor:
            # Root-owned sticky /tmp is safe for traversal, but never the
            # actual storage directory; all other writable ancestors deny.
            sticky_root = (info.st_uid == 0 and
                           info.st_mode & stat.S_ISVTX and
                           info.st_mode & stat.S_IWOTH)
            if info.st_uid not in (0, uid) or (info.st_mode & 0o022 and not sticky_root):
                raise StoragePolicyError()
        elif info.st_uid != uid or info.st_mode & 0o077:
            raise StoragePolicyError()
    elif (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
          or info.st_mode & 0o077 or info.st_nlink != 1):
        raise StoragePolicyError()


def audit_private_sqlite(directory, filename):
    """Inspect DB, -wal and -shm via dir_fd and O_NOFOLLOW, without opening SQLite.

    This is a point-in-time *diagnostic*, not authority to connect afterwards.
    """
    if type(directory) not in (str, Path) or type(filename) is not str:
        raise StoragePolicyError()
    path = str(directory)
    if not path.startswith("/") or "//" in path or path.endswith("/.."):
        raise StoragePolicyError()
    if (re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\.sqlite", filename)
            is None or filename.startswith(".") or ".." in filename):
        raise StoragePolicyError()
    uid = os.geteuid()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    opened = []
    try:
        fd = os.open("/", flags)
        opened.append(fd)
        parts = path.split("/")[1:]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise StoragePolicyError()
        for index, part in enumerate(parts):
            child = os.open(part, flags, dir_fd=fd)
            opened.append(child)
            info = os.fstat(child)
            _mode_secure(info, uid, directory=True, ancestor=index < len(parts)-1)
            fd = child
        checked = []
        for name in (filename, filename + "-wal", filename + "-shm"):
            try:
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=fd)
            except FileNotFoundError:
                if name == filename:
                    raise StoragePolicyError()
                continue
            opened.append(child)
            info = os.fstat(child)
            _mode_secure(info, uid)
            # Detect a swap between open and anchored path stat.
            pathname = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (pathname.st_dev, pathname.st_ino) != (info.st_dev, info.st_ino):
                raise StoragePolicyError()
            checked.append(name)
        return StorageReport(tuple(checked), uid)
    except (OSError, ValueError, TypeError):
        raise StoragePolicyError() from None
    finally:
        for handle in reversed(opened):
            os.close(handle)
