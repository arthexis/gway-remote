"""Firefox native messaging host for explicitly delegated Reports tabs."""
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import sys
import time
from urllib.parse import urlsplit

from .browser_contract import (MAX, TIMEOUT, check_peer, encode, receive,
                               socket_path, validate_request, validate_result)

POLICY = Path("/etc/gway-browser/policy.json")
LEASE_SECONDS = 600

def policy():
    info = POLICY.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 1024:
        raise PermissionError("unsafe_policy")
    value = json.loads(POLICY.read_bytes())
    if type(value) is not dict or set(value) != {"origin"} or type(value["origin"]) is not str:
        raise ValueError("invalid_policy")
    origin = value["origin"]
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.port is not None
            or origin != "https://" + parsed.hostname):
        raise ValueError("invalid_origin")
    return origin

def browser_read(deadline):
    def read(size):
        with selectors.DefaultSelector() as sel:
            sel.register(0, selectors.EVENT_READ)
            if not sel.select(max(0, deadline - time.monotonic())):
                raise TimeoutError("browser_timeout")
        return os.read(0, size)
    return receive(read)

def browser_send(value):
    data = encode(value)
    # The pipe is bounded; avoid a blocked writer if Firefox stops reading.
    deadline = time.monotonic() + TIMEOUT
    os.set_blocking(1, False)
    while data:
        with selectors.DefaultSelector() as sel:
            sel.register(1, selectors.EVENT_WRITE)
            if not sel.select(max(0, deadline - time.monotonic())):
                raise TimeoutError("browser_timeout")
        try:
            data = data[os.write(1, data):]
        except BlockingIOError:
            continue

def serve():
    if os.geteuid() == 0 or socket.gethostname() != "gway-001":
        raise PermissionError("canary_only")
    origin = policy()
    browser_send({"origin": origin, "lease_seconds": LEASE_SECONDS})
    if browser_read(time.monotonic() + TIMEOUT) != {"consent": True}:
        raise PermissionError("consent_required")
    path = socket_path()
    os.umask(0o077)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("unsafe_runtime_directory")
    # Only one consent lease; never remove another host's live socket.
    with (path.parent / "bridge.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise PermissionError("unsafe_existing_socket")
            path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(1)
            try:
                # Consent is not readiness: notify Firefox only after bind/listen.
                browser_send({"bridge_ready": True})
                end = time.monotonic() + LEASE_SECONDS
                with selectors.DefaultSelector() as sel:
                    sel.register(server, selectors.EVENT_READ)
                    sel.register(0, selectors.EVENT_READ)
                    while time.monotonic() < end:
                        events = sel.select(max(0, end - time.monotonic()))
                        # EOF or unsolicited browser message revokes the lease.
                        if any(key.fileobj == 0 for key, _ in events):
                            break
                        if not events:
                            break
                        conn, _ = server.accept()
                        with conn:
                            conn.settimeout(1)
                            try:
                                check_peer(conn)
                                req = validate_request(receive(conn.recv))
                            except (OSError, ValueError, EOFError):
                                continue
                            # Any uncertain action terminates the lease. No automatic retry.
                            if policy() != origin:
                                break
                            browser_send(req)
                            result = validate_result(browser_read(min(end, time.monotonic() + TIMEOUT - 1)))
                            conn.sendall(encode(result))
            finally:
                path.unlink(missing_ok=True)

def main():
    def stop(_signal, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        serve()
    except (OSError, ValueError, EOFError, RuntimeError):
        # Never send exception strings, page content or local paths to Firefox/logs.
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
