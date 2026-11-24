"""Review candidate: private Feed enrollment on the existing isolated USB canary.

No production credential store, arbitrary ADB arguments or persistent tunnel.
The field operation is deliberately not registered as a general deployment recipe.
"""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import re
import subprocess

from . import android_canary_field as field
from .android_canary_provision import validate_artifact, _private_command
from .activity_feed_canary import PORT, session, SOURCE, EVENT_TYPE
from .activity_feed_cli import HTTPSPublisher, route_binding
from .activity_feed_outbox import Outbox
from .activity_feed_maintenance import copy_database, status
from urllib.request import build_opener, ProxyHandler, HTTPSHandler
from .activity_feed_cli import NoRedirect
import ssl

SEED = "files/.gway-feed-once"
TEST = "com.arthexis.gwayremote.FeedCanaryProvisionTest"
MAPPING = f"tcp:{PORT}"


def pipe_bundle(serial, *, reader, der):
    if not re.fullmatch(r"gwr_[a-f0-9]{24}_[A-Za-z0-9_-]{1,128}", reader):
        raise ValueError("invalid reader")
    if not 0 < len(der) <= 8192:
        raise ValueError("invalid certificate size")
    payload = json.dumps({"reader":reader,"certificate":base64.b64encode(der).decode("ascii")},
                         separators=(",",":")).encode("ascii")
    for args in (("mkdir","-p","files"),("chmod","700","files")):
        if _private_command(serial,*args).returncode:
            raise RuntimeError("private directory unavailable")
    try:
        result = subprocess.run(["adb","-s",serial,"shell","-T","run-as",field.APP,
                                 "dd","of="+SEED,"bs=128"],input=payload,
                                capture_output=True,timeout=15,check=False)
        if result.returncode or _private_command(serial,"chmod","600",SEED).returncode:
            raise RuntimeError("private write failed")
        mode = _private_command(serial,"ls","-l",SEED)
        words = mode.stdout.decode("utf-8",errors="replace").split()
        if mode.returncode or not words or words[0] != "-rw-------":
            raise RuntimeError("private handoff mode unconfirmed")
        result = _private_command(serial,"sha256sum",SEED)
        words = result.stdout.decode("ascii",errors="replace").split()
        if result.returncode or not words or not hmac.compare_digest(words[0],hashlib.sha256(payload).hexdigest()):
            raise RuntimeError("private handoff checksum mismatch")
    except BaseException:
        _private_command(serial,"rm","-f",SEED)
        raise


def _has_mapping(output):
    return any(MAPPING in line.split()[1:] for line in output.splitlines())


@contextmanager
def tunnel(serial):
    if _has_mapping(field.adb(serial,"reverse","--list",timeout=10)):
        raise RuntimeError("USB feed port already allocated")
    # --no-rebind refuses a competing mapping; do not touch other ports.
    field.adb(serial,"reverse","--no-rebind",MAPPING,MAPPING,timeout=10)
    try:
        if not any(line.split()[-2:] == [MAPPING, MAPPING]
                   for line in field.adb(serial,"reverse","--list",timeout=10).splitlines()):
            raise RuntimeError("USB mapping unconfirmed")
        yield
    finally:
        field.adb(serial,"reverse","--remove",MAPPING,timeout=10)
        if _has_mapping(field.adb(serial,"reverse","--list",timeout=10)):
            raise RuntimeError("USB mapping cleanup unconfirmed")


def synthetic(session_state):
    state = session_state
    path = state["queue"]/"writer"
    path.write_text(state["writer"],encoding="ascii")
    path.chmod(0o600)
    cfg = {"endpoint":f"https://127.0.0.1:{PORT}/api/feed/events","source":SOURCE,
           "node":"gway-001","principal":state["principal"],"token_file":str(path)}
    box = Outbox(state["queue"]/"outbox",binding=route_binding(cfg))
    event = {"specversion":"1.0","source":SOURCE,"id":"canary-705","type":EVENT_TYPE,
             "time":"2026-11-24T00:00:00Z","data":{"title":"Synthetic feed canary",
             "summary":"No business data","category":"general","severity":"info","node":"gway-001"}}
    opener = build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(
        context=ssl.create_default_context(cafile=str(state["cert"]))))
    box.enqueue(event)
    publisher = HTTPSPublisher(cfg,opener=opener)
    if box.flush(publisher)["delivered"] != 1:
        raise RuntimeError("synthetic delivery failed")
    if publisher(event) != "delivered" or len(state["store"].list_after()["items"]) != 1:
        raise RuntimeError("synthetic replay not deduplicated")
    if box.metrics()["pending"] != 0:
        raise RuntimeError("synthetic queue not drained")
    copy_database(state["store"].path,state["backup"]/"snapshot.sqlite")
    if status(state["backup"]/"snapshot.sqlite")["events"] != 1:
        raise RuntimeError("snapshot verification failed")


def run(*, pr, sha, run_id, directory, central, producer, backup):
    """Only after review/authorization; exact artifact and dedicated volumes required."""
    if pr != 706:
        raise ValueError("feed canary PR not approved")
    validate_artifact(pr=pr,sha=sha,run_id=run_id,directory=directory)
    serial = field.usb()
    # Do not wake or alter global screen settings; fail if not ready.
    field.device_ready(serial,wake=False)
    with session(central,producer,backup) as state:
        synthetic(state)
        field.install(serial,directory,allow_canary_reset=False)
        with tunnel(serial):
            try:
                pipe_bundle(serial,reader=state["reader"],der=state["der"])
                result = field.adb(serial,"shell","am","instrument","-w","-r",
                                   "-e","gway_feed_usb","v1","-e","class",TEST,
                                   f"{field.TEST}/{field.RUNNER}",timeout=100)
                if "OK (1 test)" not in result or "INSTRUMENTATION_CODE: -1" not in result:
                    raise RuntimeError("feed canary instrumentation failed")
            finally:
                _private_command(serial,"rm","-f",SEED)
                _private_command(serial,"rm","-f","no_backup/feed-canary-cert.der")
                field.adb(serial,"shell","am","force-stop",field.APP,timeout=10)
    return {"status":"passed","source_sha":sha,"run_id":run_id,"synthetic_receipts":1,
            "android_tls":"verified","temporary_session":"removed"}
