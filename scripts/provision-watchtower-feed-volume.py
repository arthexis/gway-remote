#!/usr/bin/env python3
"""Watchtower-only fixed volume provisioning; no physical device formatting."""
import os
from pathlib import Path
import pwd
import grp
import re
import stat
import subprocess
import sys
import tempfile

BACKING = Path("/var/lib/gwayfeed-image")
IMAGE = BACKING / "feed.ext4"
MOUNT = Path("/var/lib/gwayfeed")
SIZE = 512 * 1024 * 1024

def root_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("expected root-private directory")

def image_identity(info):
    # Physical allocation may change after a filesystem trim; ownership,
    # link count, logical length and file type must never change.
    if not stat.S_ISREG(info.st_mode):
        raise PermissionError("backing file is not regular")
    if info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("backing file is not root-private")
    if info.st_nlink != 1:
        raise PermissionError("backing file has unexpected links")
    if info.st_size != SIZE:
        raise PermissionError("backing file has unexpected logical size")
    return info

def image_check():
    info = image_identity(IMAGE.lstat())
    if info.st_blocks * 512 < SIZE:
        raise PermissionError("backing file allocation incomplete")
    return info

def verify_mount(*, require_allocation=True):
    info = image_identity(IMAGE.lstat())
    if not os.path.ismount(MOUNT):
        raise RuntimeError("dedicated mount absent")
    out = subprocess.check_output(["findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS",
                                   "--mountpoint", str(MOUNT)], text=True).strip().split()
    if len(out) != 3 or not re.fullmatch(r"/dev/loop[0-9]+", out[0]) or out[1] != "ext4":
        raise RuntimeError("unexpected dedicated filesystem")
    backing = Path("/sys/class/block") / Path(out[0]).name / "loop/backing_file"
    if backing.read_text().strip() != str(IMAGE) or not {"nodev","nosuid","noexec","rw"} <= set(out[2].split(",")):
        raise RuntimeError("unexpected mount backing or flags")
    fs = os.statvfs(MOUNT)
    if not 256*1024*1024 <= fs.f_blocks*fs.f_frsize <= SIZE:
        raise RuntimeError("unexpected filesystem capacity")
    # A replaced pathname must not authorize mutation of a different inode.
    # losetup exposes the active backing inode independently of its path.
    loop = out[0]
    identity = subprocess.check_output(
        ["losetup", "--list", "--noheadings", "--raw",
         "--output", "BACK-INO,OFFSET,SIZELIMIT", loop],
        text=True, timeout=5).strip().split()
    if identity != [str(info.st_ino), "0", "0"]:
        raise PermissionError("unexpected loop backing inode or geometry")
    if require_allocation:
        image_check()
    return info

def restore_reservation():
    # Only the already mounted, independently identified existing file may
    # be repaired. posix_fallocate preserves the bytes in allocated extents
    # and the logical file size; no mkfs, truncate, discard or remount.
    before = verify_mount(require_allocation=False)
    if before.st_blocks * 512 >= SIZE:
        return False
    fd = os.open(IMAGE, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        current = image_identity(os.fstat(fd))
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise PermissionError("backing identity changed")
        # Reserve the entire missing allocation plus a host safety margin.
        missing = max(0, SIZE - current.st_blocks * 512)
        fs = os.fstatvfs(fd)
        if fs.f_bavail * fs.f_frsize < missing + 256 * 1024 * 1024:
            raise RuntimeError("insufficient space to restore Feed reservation")
        os.posix_fallocate(fd, 0, SIZE)
        os.fsync(fd)
        after = image_identity(os.fstat(fd))
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise PermissionError("backing identity changed")
        if after.st_blocks * 512 < SIZE:
            raise PermissionError("backing allocation could not be restored")
        final = verify_mount()
        if (final.st_dev, final.st_ino) != (before.st_dev, before.st_ino):
            raise PermissionError("backing identity changed")
        return True
    finally:
        os.close(fd)

def prepare():
    if Path("/var/lib").resolve() != Path("/var/lib"):
        raise PermissionError("unexpected filesystem root")
    BACKING.mkdir(mode=0o700, exist_ok=True)
    root_directory(BACKING)
    if MOUNT.is_symlink():
        raise PermissionError("mount symlink")
    if MOUNT.exists():
        if os.path.ismount(MOUNT):
            return restore_reservation()
        else:
            root_directory(MOUNT)
            if any(MOUNT.iterdir()):
                raise PermissionError("unmanaged mount contents")
    else:
        MOUNT.mkdir(mode=0o700)
    if IMAGE.exists() or IMAGE.is_symlink():
        image_check()
        return False
    if os.path.ismount(MOUNT):
        raise PermissionError("unexpected existing mount")
    fs = os.statvfs(BACKING)
    if fs.f_bavail*fs.f_frsize < SIZE + 256*1024*1024:
        raise RuntimeError("insufficient space for dedicated Feed storage")
    fd, name = tempfile.mkstemp(dir=BACKING, prefix=".feed-new-")
    try:
        os.posix_fallocate(fd, 0, SIZE)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        # Only the exclusive, newly allocated regular file is formatted.
        subprocess.run(["mkfs.ext4","-q","-F","-E","nodiscard","-m","0",name], check=True,
                       timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(name,"rb") as stream:
            os.fsync(stream.fileno())
        os.link(name, IMAGE)
        os.unlink(name)
        dirfd = os.open(BACKING, os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        image_check()
        return True
    finally:
        if fd >= 0:
            os.close(fd)
        Path(name).unlink(missing_ok=True)

def finish():
    verify_mount()
    uid = pwd.getpwnam("gway-mcp-gateway").pw_uid
    gid = grp.getgrnam("gway-mcp-read").gr_gid
    info = MOUNT.lstat()
    if info.st_uid not in (0, uid) or not stat.S_ISDIR(info.st_mode):
        raise PermissionError("unexpected mount owner")
    changed = info.st_uid != uid or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o700
    if changed:
        os.chown(MOUNT, uid, gid)
        os.chmod(MOUNT, 0o700)
    return changed

if __name__ == "__main__":
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ("prepare","finish"):
        raise SystemExit("fixed root-owned Feed volume operation required")
    print("changed=" + str((prepare if sys.argv[1] == "prepare" else finish)()).lower())
