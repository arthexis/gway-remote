"""Loopback-only Watchtower enrollment HTTP presentation and service entrypoint.

The enrollment contract and error responses are unchanged. The standalone
client artifact stays in this package directory without importing it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .bootstrap_script import render_bootstrap_script
from .watchtower_enrollment_ledger import EnrollmentRejected
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .deferred_enrollment import DeferredPreparations
from .watchtower_enrollment_provisioner import Provisioner
from .wireguard_enrollment_contract import (
    InvalidEnrollment, MAX_REQUEST_BYTES, parse_host_identity_enrollment,
    validate_enrollment,
)


def make_handler(provisioner: Provisioner | None, *, public_url: str, wireguard_endpoint: str,
                 read_only_stage: bool = False, deferred: DeferredPreparations | None = None):
    if deferred is not None:
        from .deferred_enrollment import PreparationRejected
    class Handler(BaseHTTPRequestHandler):
        server_version = "gway-remote-watchtower"
        sys_version = ""

        def log_message(self, *_args) -> None:
            return

        def _send(self, status: int, payload: dict) -> None:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(encoded)

        def _script(self, secret: str, device: str, server_key: str,
                    *, repair_host_identity: bool = False) -> bytes:
            """HTTPS-distributed stage-one script; never includes an invitation token."""
            # URL bearer characters are restricted by the route regexp.
            return render_bootstrap_script(secret, device, server_key,
                                           repair_host_identity=repair_host_identity)

        def _send_artifact(self, data: bytes, media_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", media_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self) -> None:
            from urllib.parse import urlsplit
            parsed_path = urlsplit(self.path)
            bootstrap_match = re.fullmatch(
                r"/v1/bootstrap/([A-Za-z0-9_-]{32,128})(/client\.py)?", parsed_path.path,
            )
            if bootstrap_match and not read_only_stage and provisioner is not None:
                try:
                    session = provisioner.ledger.bootstrap_session(bootstrap_match.group(1))
                    expected_query = "replace=true" if session["replace"] and not bootstrap_match.group(2) else ""
                    if parsed_path.query != expected_query or parsed_path.fragment:
                        raise EnrollmentRejected("bootstrap rejected")
                    if session["replace"]:
                        # No replacement transaction is implemented yet: never present a regular
                        # enrollment script as a valid replacement operation.
                        raise EnrollmentRejected("replacement bootstrap not yet supported")
                    if bootstrap_match.group(2):
                        data = Path(__file__).with_name("wireguard_satellite.py").read_bytes()
                        self._send_artifact(data, "text/x-python; charset=utf-8")
                    else:
                        key = subprocess.run(
                            ["wg", "show", "gway", "public-key"], check=True,
                            capture_output=True, text=True,
                        ).stdout.strip()
                        self._send_artifact(
                            self._script(bootstrap_match.group(1), session["device"], key,
                                         repair_host_identity=session["repair_host_identity"]),
                            "text/x-shellscript; charset=utf-8",
                        )
                except (EnrollmentRejected, OSError, subprocess.CalledProcessError):
                    self._send(404, {"error": "not_found"})
                return
            # Feature-gated; never active until an operator supplies the
            # separately protected sealing key and enables the deferred store.
            challenge = re.fullmatch(r"/v1/sd-preparations/([a-f0-9]{32})/challenge", self.path)
            if challenge and not read_only_stage and deferred is not None and self.command == "GET":
                try:
                    nonce = deferred.challenge(challenge.group(1))
                except PreparationRejected:
                    self._send(404, {"error": "not_found"})
                else:
                    self._send(200, {"challenge": nonce})
                return
            if self.path == "/health":
                self._send(200, {"ok": True, "service": "gway-remote-watchtower", "enrollment_url": public_url})
            else:
                self._send(404, {"error": "not_found"})

        do_HEAD = do_GET

        def do_POST(self) -> None:
            claim = re.fullmatch(r"/v1/sd-preparations/([a-f0-9]{32})/claim", self.path)
            if claim and not read_only_stage and deferred is not None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024:
                        raise ValueError("bad length")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict) or set(data) != {"challenge", "signature"}:
                        raise ValueError("invalid fields")
                    result = deferred.claim(claim.group(1), data["challenge"], data["signature"])
                except (ValueError, TypeError, KeyError):
                    self._send(400, {"error": "invalid_request"})
                except PreparationRejected:
                    self._send(403, {"error": "preparation_rejected"})
                else:
                    # Contains one secret URL: never log response body.
                    self._send(200, result)
                return
            completion = re.fullmatch(
                r"/v1/bootstrap/([A-Za-z0-9_-]{32,128})/complete", self.path,
            )
            if completion and not read_only_stage and provisioner is not None:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 1024:
                        raise ValueError("bad request")
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict) or set(data) != {"device", "public_key"}:
                        raise ValueError("bad request")
                    device, public_key, _session = validate_enrollment(
                        {"device": data["device"], "public_key": data["public_key"],
                         "token": completion.group(1)}
                    )
                    provisioner.ledger.complete_bootstrap(completion.group(1), device, public_key)
                except (ValueError, TypeError, KeyError):
                    self._send(400, {"error": "invalid_request"})
                except EnrollmentRejected:
                    self._send(403, {"error": "enrollment_rejected"})
                else:
                    self._send(200, {"complete": True})
                return
            if self.path != "/v1/enroll":
                self._send(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST_BYTES:
                    raise InvalidEnrollment("invalid enrollment request")
                device, public_key, token, ssh_host_key, repair_host_identity = parse_host_identity_enrollment(self.rfile.read(length))
                if read_only_stage:
                    raise EnrollmentRejected("enrollment rejected")
                if provisioner is None:
                    raise RuntimeError("Watchtower provisioner is unavailable")
                if repair_host_identity:
                    enrollment = provisioner.repair_host_identity(
                        device, public_key, token, ssh_host_key=ssh_host_key,
                    )
                else:
                    enrollment = (provisioner.enroll(device, public_key, token, ssh_host_key=ssh_host_key)
                                  if ssh_host_key is not None else provisioner.enroll(device, public_key, token))
            except (InvalidEnrollment, ValueError):
                self._send(400, {"error": "invalid_request"})
            except EnrollmentRejected:
                self._send(403, {"error": "enrollment_rejected"})
            except Exception:
                self._send(500, {"error": "enrollment_failed"})
            else:
                self._send(200, {"device": enrollment.device, "address": enrollment.address, "public_key": enrollment.public_key, "server_endpoint": wireguard_endpoint, "server_public_key": subprocess.run(["wg", "show", "gway", "public-key"], check=True, capture_output=True, text=True).stdout.strip(), "server_tunnel_ip": str(provisioner.ledger.gateway), "enrollment_url": public_url, "created": not enrollment.already_active, "repaired": repair_host_identity})
    return Handler


def serve(provisioner: Provisioner | None, *, host: str, port: int, public_url: str,
          wireguard_endpoint: str, read_only_stage: bool = False,
          deferred: DeferredPreparations | None = None) -> None:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("Watchtower service must bind a loopback address")
    if read_only_stage:
        if provisioner is not None:
            raise ValueError("read-only stage must not receive a provisioner")
    elif provisioner is None:
        raise ValueError("active Watchtower service requires a provisioner")
    else:
        provisioner.recover()
    # Feature OFF by default. A protected 0600 root-owned key must be
    # deliberately installed before the loopback API can accept claims.
    if os.environ.get("GWAY_SD_PREPARATIONS_ENABLED") == "1":
        if read_only_stage or provisioner is None or deferred is not None:
            raise ValueError("invalid deferred enrollment activation")
        from .deferred_enrollment_cli import read_sealing_key
        from .deferred_enrollment import DeferredPreparations
        deferred = DeferredPreparations(
            provisioner.ledger.path,
            sealing_key=read_sealing_key(Path("/etc/gway-remote/sd-sealing.key")))
    httpd = ThreadingHTTPServer((host, port), make_handler(
        provisioner, public_url=public_url, wireguard_endpoint=wireguard_endpoint,
        read_only_stage=read_only_stage, deferred=deferred))
    httpd.serve_forever()
