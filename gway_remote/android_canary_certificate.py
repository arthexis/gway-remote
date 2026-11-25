"""Read-only certificate evidence from the physical canary; no app data access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile

from gway_remote.android_canary_install import CANARY, PRODUCTION, authorized_usb, require_success, run_command, InstallBlocked


def certificate_sha256(apk):
    """Extract the single v2 signer certificate (not a signature verifier)."""
    data = Path(apk).read_bytes()
    def uint(buf, offset=0):
        return struct.unpack_from("<I", buf, offset)[0]
    def ulong(buf, offset=0):
        return struct.unpack_from("<Q", buf, offset)[0]
    def lp(buf, offset=0):
        size = uint(buf, offset)
        end = offset + 4 + size
        if end > len(buf):
            raise ValueError("truncated length")
        return buf[offset + 4:end], end
    try:
        eocd = data.rfind(b"PK\x05\x06", max(0, len(data)-65557))
        if eocd < 0 or eocd + 22 + struct.unpack_from("<H", data, eocd+20)[0] != len(data):
            raise ValueError("invalid ZIP end")
        cd = uint(data, eocd+16)
        if not 32 <= cd <= eocd or data[cd-16:cd] != b"APK Sig Block 42":
            raise ValueError("missing signing block")
        size = ulong(data, cd-24)
        start = cd-size-8
        if start < 0 or ulong(data, start) != size:
            raise ValueError("invalid signing block")
        pos = start+8
        v2 = None
        while pos < cd-24:
            n = ulong(data, pos)
            end = pos+8+n
            if n < 4 or end > cd-24:
                raise ValueError("invalid block entry")
            if uint(data, pos+8) == 0x7109871a:
                if v2 is not None:
                    raise ValueError("duplicate v2 block")
                v2 = data[pos+12:end]
            pos = end
        if pos != cd-24 or v2 is None:
            raise ValueError("missing v2")
        signers, end = lp(v2)
        signer, signer_end = lp(signers)
        if end != len(v2) or signer_end != len(signers):
            raise ValueError("multiple or malformed signers")
        signed, _ = lp(signer)
        _, pos = lp(signed)
        certs, _ = lp(signed, pos)
        cert, _ = lp(certs)
        if not cert:
            raise ValueError("empty certificate")
        return hashlib.sha256(cert).hexdigest()
    except (ValueError, struct.error) as exc:
        raise InstallBlocked("unsupported_or_malformed_apk_signing_block") from exc


def installed_evidence(package=CANARY, call=run_command):
    if package not in (CANARY, PRODUCTION):
        raise InstallBlocked("package_not_allowed")
    serial = authorized_usb(call)
    def adb(*args, timeout=30):
        return call(["/usr/bin/adb", "-s", serial, *args], timeout)
    output = require_success(adb("shell", "pm", "path", package), "canary_package_inspection_failed")
    paths = [line.removeprefix("package:") for line in output.splitlines()
             if re.fullmatch(r"package:/data/app/[A-Za-z0-9._=~/-]+/base\.apk", line)]
    if len(paths) != 1:
        raise InstallBlocked("canary_base_apk_not_unique")
    with tempfile.TemporaryDirectory() as tmp:
        apk = Path(tmp) / "base.apk"
        require_success(adb("pull", paths[0], str(apk), timeout=90), "canary_apk_read_failed")
        if not apk.is_file() or not 0 < apk.stat().st_size < 104857600:
            raise InstallBlocked("invalid_canary_base_apk")
        info = require_success(adb("shell", "dumpsys", "package", package), "package_version_inspection_failed")
        versions = set(re.findall(r"(?m)^\s*versionCode=(\d+)(?:\s|$)", info))
        if len(versions) != 1:
            raise InstallBlocked("package_version_unconfirmed")
        return {"package": package, "certificate_sha256": certificate_sha256(apk),
                "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
                "version_code": int(versions.pop()), "scope": "installed_apk_v2_certificate_evidence"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stable", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(installed_evidence(PRODUCTION if args.stable else CANARY)))
    except InstallBlocked as exc:
        raise SystemExit(str(exc))
