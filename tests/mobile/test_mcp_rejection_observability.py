"""No real provider, credentials or external network."""
import contextlib
import io
import json
import re
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server
from gway_remote.mcp_gateway_federation import FederatedProviders
from tests.helpers.mcp_http import bearer_post, mcp_call
from tests.mobile.test_mcp_canonical_routing_http import Transport


class RejectionObservabilityTests(unittest.TestCase):
    def test_rejection_correlation_and_redaction(self):
        transport = Transport()
        federation = FederatedProviders(transport=transport,
            nodes=lambda: ("gway-001", "gway-004"), canonical=True)
        with tempfile.TemporaryDirectory() as directory:
            registry = BearerRegistry(Path(directory) / "gateway.db")
            token = registry.issue()
            with make_server(("127.0.0.1", 0), BearerVerifier(registry.path),
                    "http://127.0.0.1:1/mcp", "backend-secret-sentinel",
                    federation=federation) as gateway:
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                log = io.StringIO()
                endpoint = "http://127.0.0.1:%d/mcp" % gateway.server_port

                def call(name, args, origin=False):
                    req = bearer_post(endpoint, mcp_call(name, args), token)
                    req.add_header("X-Gway-Request-ID", "untrusted-id-sentinel")
                    if origin:
                        req.add_header("Origin", "https://origin-sentinel.invalid")
                    try:
                        with urlopen(req, timeout=5):
                            raise AssertionError("unexpected successful dispatch")
                    except HTTPError as exc:
                        with exc:
                            return exc.code, exc.headers["X-Gway-Request-ID"]

                try:
                    with contextlib.redirect_stderr(log):
                        first = call("agentops__status", {}, True)
                        second = call("agentops__submit", {"node": "gway-004"})
                        with ThreadPoolExecutor(max_workers=4) as pool:
                            rest = list(pool.map(lambda _: call("agentops__status",
                                {"node": "unknown-sentinel"}), range(4)))
                    assert first[0] == 403
                    assert second[0] == 401
                    assert all(code == 403 for code, _ in rest)
                    ids = [rid for _, rid in [first, second, *rest]]
                    assert len(set(ids)) == 6
                    assert all(re.fullmatch(r"[0-9a-f]{32}", rid) for rid in ids)
                    lines = [json.loads(line.split(" ", 1)[1])
                             for line in log.getvalue().splitlines()
                             if line.startswith("gway_mcp_rejection ")]
                    assert len(lines) == 6
                    by_id = {row["request_id"]: row for row in lines}
                    assert set(by_id) == set(ids)
                    assert by_id[first[1]]["reason_code"] == "origin_header"
                    assert by_id[second[1]]["reason_code"] == "insufficient_scope"
                    for code, rid in [first, second, *rest]:
                        assert by_id[rid]["http_status"] == code
                        assert by_id[rid]["route"] == "mcp"
                        assert by_id[rid]["origin"] == "watchtower_gateway"
                        assert set(by_id[rid]) == {"request_id", "http_status",
                            "route", "origin", "reason_code"}
                    for secret in (token, "backend-secret-sentinel", "unknown-sentinel",
                                   "origin-sentinel", "untrusted-id-sentinel"):
                        assert secret not in log.getvalue()
                    assert not transport.sent
                finally:
                    gateway.shutdown()
                    thread.join()
