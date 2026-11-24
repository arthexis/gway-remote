"""Review candidate: one-shot, feed-only canary receiver; never deploys Watchtower.

Only a separately authorized, node-owned field runner may activate this module.
The listener is fixed to host loopback; no reverse proxy, systemd or live grants.
"""
from contextlib import contextmanager
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import os
import ssl
import subprocess

from .activity_feed import ActivityFeedStore
from .activity_feed_http import ActivityFeedAPI, handle, is_feed_path, _respond, validate_grants
from .activity_feed_maintenance import check_volume
from .mcp_bearer import BearerRegistry, BearerVerifier

PORT = 18443
SOURCE = "/canary/705"
EVENT_TYPE = "canary.synthetic"


class FeedOnlyHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def log_message(self, *_):
        pass  # never log headers, paths or request data

    def do_GET(self):
        if not is_feed_path(self.path):
            return _respond(self, 404, {"error": "not_found"})
        return handle(self, "GET")

    def do_POST(self):
        if self.path != "/api/feed/events":
            return _respond(self, 404, {"error": "not_found"})
        return handle(self, "POST")


class FeedOnlyServer(HTTPServer):
    allow_reuse_address = False

    def get_request(self):
        # Accept and handshake within a fixed timeout, not in the listening socket.
        sock, addr = self.socket.accept()
        sock.settimeout(5)
        try:
            return self.tls.wrap_socket(sock, server_side=True), addr
        except BaseException:
            sock.close()
            raise


@contextmanager
def session(central, producer, backup):
    """Use three verified dedicated volumes; never create or mount a filesystem."""
    roots = tuple(Path(p) for p in (central, producer, backup))
    if len(set(roots)) != 3 or len({p.stat().st_dev for p in roots}) != 3:
        raise ValueError("distinct dedicated volumes required")
    for path, role in zip(roots, ("central", "producer", "backup")):
        check_volume(path, role)
    if os.geteuid() == 0:
        raise PermissionError("use existing non-root installation identity")
    with _private_session(roots) as state:
        yield state


@contextmanager
def _private_session(roots):
    """Internal lifecycle; caller must validate volume isolation first."""
    with TemporaryDirectory(dir=roots[0], prefix="feed-canary-") as c, \
         TemporaryDirectory(dir=roots[1], prefix="feed-canary-") as q, \
         TemporaryDirectory(dir=roots[2], prefix="feed-canary-") as b:
        root = Path(c)
        cert, key = root/"leaf.pem", root/"leaf.key"
        subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes",
                        "-days","1","-subj","/CN=127.0.0.1",
                        "-addext","subjectAltName=IP:127.0.0.1",
                        "-keyout",str(key),"-out",str(cert)],
                       check=True, timeout=20, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        der = ssl.PEM_cert_to_DER_cert(cert.read_text())
        registry = BearerRegistry(root/"auth.sqlite")
        verifier = BearerVerifier(root/"auth.sqlite")
        reader = registry.issue(scope="gway:read", lifetime=600)
        writer = registry.issue(scope="gway:feed-publish", lifetime=600, operator_approved=True)
        rk, wk = reader.split("_")[1], writer.split("_")[1]
        grants = validate_grants({wk: {"enabled": True, "source": SOURCE,
            "nodes":["gway-001"], "repositories":[None], "types":[EVENT_TYPE]}})
        store = ActivityFeedStore(root/"events.sqlite")
        api = ActivityFeedAPI(store, verifier, lambda: grants)
        srv = FeedOnlyServer(("127.0.0.1", PORT), FeedOnlyHandler)
        thread = None
        try:
            srv.activity_feed = api
            srv.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            srv.tls.load_cert_chain(cert, key)
            thread = Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            yield {"reader":reader,"writer":writer,"principal":wk,"der":der,
                   "cert":cert,"store":store,"queue":Path(q),"backup":Path(b),
                   "port":srv.server_port}
        finally:
            try:
                registry.revoke(rk)
            finally:
                try:
                    registry.revoke(wk)
                finally:
                    if thread is not None and thread.is_alive():
                        srv.shutdown()
                        thread.join(8)
                    srv.server_close()
