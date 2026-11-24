"""Review candidate: private Feed enrollment on the existing isolated USB canary.

No production credential store, arbitrary ADB arguments or persistent tunnel.
The field operation is deliberately not registered as a general deployment recipe.
"""
import argparse
import base64
import os
from pathlib import Path
import socket
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
from .activity_feed import validate_event
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


def _owned_mapping(output):
    return sum(line.split()[-2:] == [MAPPING, MAPPING] for line in output.splitlines()) == 1


@contextmanager
def tunnel(serial):
    if _has_mapping(field.adb(serial,"reverse","--list",timeout=10)):
        raise RuntimeError("USB feed port already allocated")
    # --no-rebind refuses a competing mapping; do not touch other ports.
    field.adb(serial,"reverse","--no-rebind",MAPPING,MAPPING,timeout=10)
    try:
        if not _owned_mapping(field.adb(serial,"reverse","--list",timeout=10)):
            raise RuntimeError("USB mapping unconfirmed")
        yield
    finally:
        current = field.adb(serial,"reverse","--list",timeout=10)
        if _has_mapping(current):
            if not _owned_mapping(current):
                raise RuntimeError("USB mapping ownership changed")
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
    event = validate_event(event)
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


CERT = "no_backup/feed-canary-cert.der"


def _absent(serial, path):
    result = _private_command(serial, "test", "!", "-e", path)
    return result.returncode == 0


def _require_empty_seed(serial):
    identity = _private_command(serial, "id", "-u")
    if identity.returncode or not re.fullmatch(rb"[0-9]+\n?", identity.stdout):
        raise RuntimeError("canary private identity unverified")
    if not all(_absent(serial, p) for p in (SEED, CERT, CERT+".bak", CERT+".new")):
        raise RuntimeError("existing canary feed state; refusing overwrite")


def _cleanup_seed(serial):
    # Run only after the private state was confirmed absent before provisioning.
    result = _private_command(serial,"rm","-f",SEED,CERT,CERT+".bak",CERT+".new")
    if result.returncode or not all(_absent(serial,p) for p in (SEED,CERT,CERT+".bak",CERT+".new")):
        raise RuntimeError("private canary cleanup unconfirmed")


def run(*, pr, sha, run_id, directory, central, producer, backup):
    """Only after review/authorization; exact artifact and dedicated volumes required."""
    if pr != 706:
        raise ValueError("feed canary PR not approved")
    validate_artifact(pr=pr,sha=sha,run_id=run_id,directory=directory)
    if socket.gethostname().split(".")[0] != "gway-001" or os.geteuid() == 0:
        raise PermissionError("field runner requires gway-001 installation identity")
    # Dedicated-volume validation and synthetic transport precede any USB mutation.
    with session(central,producer,backup) as state:
        synthetic(state)
        serial = field.usb()
        field.device_ready(serial,wake=False)
        before = field.adb(serial,"shell","pm","path",field.PRODUCTION)
        if not before.startswith("package:"):
            raise RuntimeError("production package baseline unconfirmed")
        try:
            with field.keep_usb_screen_on(serial):
                field.install(serial,directory,allow_canary_reset=False)
                field.device_ready(serial,wake=False)
                _require_empty_seed(serial)
                with tunnel(serial):
                    try:
                        pipe_bundle(serial,reader=state["reader"],der=state["der"])
                        result = field.adb(serial,"shell","am","instrument","-w","-r",
                                           "-e","gway_feed_usb","v1","-e","class",
                                           TEST+",com.arthexis.gwayremote.ActivityFeedComposeTest",
                                           f"{field.TEST}/{field.RUNNER}",timeout=180)
                        if ("OK (2 tests)" not in result or "INSTRUMENTATION_CODE: -1" not in result
                                or "FAILURES" in result):
                            raise RuntimeError("feed canary instrumentation failed")
                    finally:
                        try:
                            for package in (field.APP,field.TEST):
                                field.adb(serial,"shell","am","force-stop",package,timeout=10)
                        finally:
                            _cleanup_seed(serial)
        finally:
            if field.adb(serial,"shell","pm","path",field.PRODUCTION) != before:
                raise RuntimeError("production package path changed")
    return {"status":"passed","source_sha":sha,"run_id":run_id,"synthetic_receipts":1,
            "android_tls":"verified","compose_tests_passed":1,"temporary_session":"removed",
            "production_package_unchanged":True,"canary_apk_retained":True}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reviewed manual USB-only Feed acceptance")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path.home()/".local/state/gway-remote/feed-canary-volumes"
    try:
        result = run(pr=args.pr,sha=args.sha,run_id=args.run_id,directory=args.artifact_dir,
                     central=root/"central",producer=root/"producer",backup=root/"backup")
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception:
        # Never return subprocess output, secrets, USB serial or private paths.
        print(json.dumps({"status":"blocked","reason":"feed_canary_preflight_or_acceptance_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
