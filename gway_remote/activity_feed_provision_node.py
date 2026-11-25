"""Private producer installation through the existing pinned node protocol."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from datetime import datetime, timezone

from .activity_feed_cli import load_config, read_private, HTTPSPublisher
from .activity_feed_hooks import event

ENDPOINT = "https://remote.arthexis.com/api/feed/events"
ID = re.compile(r"[a-f0-9]{24}\Z")
TOKEN = re.compile(r"gwr_([a-f0-9]{24})_[A-Za-z0-9_-]{43}\Z")


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("unsafe private producer directory")


def config_for(node, principal, token_path):
    if not re.fullmatch(r"gway-[0-9]{3,}", node) or not ID.fullmatch(principal):
        raise ValueError("invalid producer identity")
    return {"endpoint":ENDPOINT, "source":"/nodes/"+node, "node":node,
            "principal":principal, "token_file":str(token_path)}


def atomic(path, raw):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".feed-provision-")
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


def status(node, *, home=None):
    root = (Path.home() if home is None else Path(home)) / ".config/gway-remote"
    path = root / "feed.json"
    if not path.exists() and not path.is_symlink():
        return {"configured":False}
    private_dir(root)
    cfg = load_config(path)
    token_path = Path(cfg["token_file"])
    if token_path.parent != root or not re.fullmatch(r"feed-token-[a-f0-9]{24}", token_path.name):
        raise PermissionError("existing producer not managed by provisioner")
    if cfg != config_for(node, cfg["principal"], token_path):
        raise PermissionError("existing producer binding differs")
    token = TOKEN.fullmatch(read_private(token_path, 256).decode("ascii").strip())
    if not token or token_path.name != "feed-token-"+token[1]:
        raise PermissionError("invalid existing producer credential")
    return {"configured":True,"principal":cfg["principal"],"credential_id":token[1]}


def install(node, principal, credential, *, home=None, publisher=HTTPSPublisher):
    if os.geteuid() == 0:
        raise PermissionError("installation user required")
    if not isinstance(credential, str) or not TOKEN.fullmatch(credential):
        raise ValueError("invalid provisioned token")
    child = TOKEN.fullmatch(credential)[1]
    root = (Path.home() if home is None else Path(home)) / ".config/gway-remote"
    private_dir(root)
    lockfd = os.open(root / "feed-provision.lock", os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lockfd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        old = status(node, home=home)
        if old["configured"] and old["principal"] != principal:
            raise PermissionError("producer principal changed; reconcile outbox first")
        token_path = root / ("feed-token-"+child)
        cfg = config_for(node, principal, token_path)
        if token_path.exists() or token_path.is_symlink():
            if read_private(token_path, 256) != credential.encode("ascii"):
                raise PermissionError("conflicting credential file")
        else:
            atomic(token_path, credential.encode("ascii"))
        try:
            # Real scoped HTTPS acceptance before switching the active pointer.
            value = event(source=cfg["source"], kind="feed.provisioned", identity=child,
                          at=datetime.now(timezone.utc).isoformat(), title="Feed publisher verified",
                          summary="Restricted producer delivery confirmed", category="system",
                          severity="success", node=node)
            if publisher(cfg)(value) != "delivered":
                raise RuntimeError("publisher acceptance unavailable")
            atomic(root / "feed.json", json.dumps(cfg, sort_keys=True).encode("ascii"))
        except BaseException:
            # Do not remove active credential on uncertain post-rename fsync.
            if not (root/"feed.json").exists():
                token_path.unlink(missing_ok=True)
            raise
        return {"configured":True,"principal":principal,"credential_id":child,"delivered":True}
    finally:
        os.close(lockfd)
