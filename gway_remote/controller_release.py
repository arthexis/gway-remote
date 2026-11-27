"""Verified mobile-controller deployment evidence; never infer from a checkout."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import tempfile
import uuid
import zipfile

EXECUTABLE = Path("/usr/local/bin/gway-remote")
ROOT = Path("/opt/gway-remote")
RECEIPT = ROOT / "controller-deployment.json"
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
MAX_ARCHIVE = 64 * 1024 * 1024


def _read_protected(path, limit, *, uid=0):
    path = Path(path)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid or parent.st_mode & 0o022:
        raise ValueError("unsafe evidence directory")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                or info.st_mode & 0o022 or not 0 < info.st_size <= limit):
            raise ValueError("unsafe evidence file")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        current = path.lstat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if len(data) != info.st_size or identity(info) != identity(after) or identity(info) != identity(current):
            raise ValueError("evidence changed during read")
        return data


def _archive_digest(path=EXECUTABLE):
    return hashlib.sha256(_read_protected(path, MAX_ARCHIVE)).hexdigest()


def _startup_digest():
    # The mobile API runs from the installed zipapp, not the MCP package,
    # a staged zipapp, a source checkout, or a mutable deployment marker.
    if getattr(__loader__, "archive", None) != str(EXECUTABLE):
        return None
    try:
        return _archive_digest()
    except (OSError, ValueError):
        return None


RUNNING_DIGEST = _startup_digest()


def controller_evidence(*, receipt=RECEIPT, executable=EXECUTABLE,
                        running_digest=RUNNING_DIGEST, uid=0):
    result = {"name": "gway-remote", "installed_sha": None,
              "last_successful_update": None, "evidence": "unavailable"}
    try:
        if not isinstance(running_digest, str) or not DIGEST.fullmatch(running_digest):
            return result
        current = hashlib.sha256(_read_protected(executable, MAX_ARCHIVE, uid=uid)).hexdigest()
        if current != running_digest:
            return result
        record = json.loads(_read_protected(receipt, 4096, uid=uid))
        if (not isinstance(record, dict) or set(record) !=
                {"schema", "source_sha", "executable_sha256", "verified_at"}
                or type(record["schema"]) is not int or record["schema"] != 1
                or not isinstance(record["source_sha"], str) or not SHA.fullmatch(record["source_sha"])
                or record["executable_sha256"] != current
                or not isinstance(record["verified_at"], str)):
            return result
        at = datetime.fromisoformat(record["verified_at"])
        if at.tzinfo is None or at.utcoffset() != timezone.utc.utcoffset(at) or at > datetime.now(timezone.utc):
            return result
        return {**result, "installed_sha": record["source_sha"],
                "last_successful_update": at.isoformat(), "evidence": "verified"}
    except (OSError, ValueError, TypeError):
        return result


def verify_source_package(source, revision, executable_digest, *, root=ROOT,
                          executable=EXECUTABLE, uid=0):
    """Bind the reviewed commit to both installed package archive and CLI bytes."""
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("invalid controller source revision")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], timeout=30)
    if git("rev-parse", "--verify", "HEAD").decode().strip() != revision:
        raise ValueError("controller source revision mismatch")
    archive = git("archive", "--format=tar", revision, "--", "gway_remote")
    expected = hashlib.sha256(archive).hexdigest()
    root = Path(root)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
        raise ValueError("unsafe controller installation root")
    link = root / "gway_remote"
    if not link.is_symlink() or os.readlink(link) != f".package-releases/{expected}/gway_remote":
        raise ValueError("controller package revision mismatch")
    installed = _read_protected(executable, MAX_ARCHIVE, uid=uid)
    if hashlib.sha256(installed).hexdigest() != executable_digest:
        raise ValueError("controller executable digest mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as committed:
        with zipfile.ZipFile(io.BytesIO(installed)) as built:
            names = built.namelist()
            if len(names) != len(set(names)):
                raise ValueError("duplicate controller archive entries")
            expected_files = set()
            for member in committed:
                if member.isdir():
                    continue
                if not member.isfile() or not member.name.startswith("gway_remote/"):
                    raise ValueError("unexpected controller package member")
                expected_files.add(member.name)
                stream = committed.extractfile(member)
                if stream is None or built.read(member.name) != stream.read():
                    raise ValueError("controller executable source mismatch")
            if not expected_files or "gway_remote/__main__.py" not in expected_files:
                raise ValueError("incomplete controller source archive")
            for entry in built.infolist():
                if entry.is_dir() or entry.filename in expected_files or entry.filename == "__main__.py":
                    continue
                # The installer can copy generated Python caches; do not let
                # an unexpected source module silently become verified evidence.
                if not (entry.filename.startswith("gway_remote/")
                        and "/__pycache__/" in entry.filename and entry.filename.endswith(".pyc")):
                    raise ValueError("unexpected executable package member")
            if built.read("__main__.py") != b"from gway_remote.__main__ import main\nmain()\n":
                raise ValueError("unexpected controller entrypoint")


def verified_noop(source, revision, *, root=ROOT, executable=EXECUTABLE, uid=0):
    """Require protected prior success and exact installed bytes, not the hint."""
    try:
        digest = hashlib.sha256(_read_protected(executable, MAX_ARCHIVE, uid=uid)).hexdigest()
        row = controller_evidence(receipt=root / RECEIPT.name, executable=executable,
                                  running_digest=digest, uid=uid)
        if row["installed_sha"] != revision:
            return False
        verify_source_package(source, revision, digest, root=root, executable=executable, uid=uid)
        return True
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile, tarfile.TarError):
        return False


def record_verified_deployment(source, revision, executable_digest, *, execute,
                               root=ROOT, executable=EXECUTABLE, uid=0):
    """Called only after the existing transactional install and authenticated health."""
    verify_source_package(source, revision, executable_digest, root=root,
                          executable=executable, uid=uid)
    record = {"schema": 1, "source_sha": revision,
              "executable_sha256": executable_digest,
              "verified_at": datetime.now(timezone.utc).isoformat()}
    root = Path(root)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
        raise ValueError("unsafe controller receipt directory")
    receipt = root / RECEIPT.name
    pending = root / (".controller-deployment-" + uuid.uuid4().hex)
    with tempfile.TemporaryDirectory() as temp:
        payload = Path(temp) / "receipt.json"
        payload.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        try:
            execute("sudo", "-n", "install", "-o", "root", "-g", "root", "-m", "0644",
                    str(payload), str(pending))
            # Recheck the exact executable before publishing the receipt.
            if _read_protected(pending, 4096, uid=uid) != payload.read_bytes():
                raise ValueError("staged controller receipt mismatch")
            if hashlib.sha256(_read_protected(executable, MAX_ARCHIVE, uid=uid)).hexdigest() != executable_digest:
                raise ValueError("controller executable changed before receipt")
            # Same-directory rename is the publication boundary. A failed
            # command can be ambiguous: accept only exact protected readback.
            try:
                execute("sudo", "-n", "mv", "-T", "--", str(pending), str(receipt))
            except (OSError, subprocess.SubprocessError):
                if pending.exists() or _read_protected(receipt, 4096, uid=uid) != payload.read_bytes():
                    raise
        finally:
            if pending.exists():
                execute("sudo", "-n", "rm", "-f", "--", str(pending))
