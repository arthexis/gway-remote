#!/usr/bin/env python3
"""Render public Android Digital Asset Links without reading signing secrets.

Offline only. Does NOT install nginx, restart services or enable the issuer.
Use the *actual release APK* signer fingerprint from a verified GitHub release.
"""
import argparse
import base64
import binascii
import json
import re
from pathlib import Path

PACKAGE = "com.arthexis.gwayremote"
ORIGIN_PREFIX = "android:apk-key-hash:"


def render(fingerprint):
    if type(fingerprint) is not str:
        raise ValueError("invalid_certificate_fingerprint")
    hex_value = fingerprint.replace(":", "").upper()
    if not re.fullmatch(r"[0-9A-F]{64}", hex_value):
        raise ValueError("invalid_certificate_fingerprint")
    cert = binascii.unhexlify(hex_value)
    canonical = ":".join(hex_value[i:i+2] for i in range(0, 64, 2))
    origin = ORIGIN_PREFIX + base64.urlsafe_b64encode(cert).decode("ascii").rstrip("=")
    statements = [{
        "relation": ["delegate_permission/common.get_login_creds"],
        "target": {
            "namespace": "android_app",
            "package_name": PACKAGE,
            "sha256_cert_fingerprints": [canonical],
        },
    }]
    return json.dumps(statements, indent=2) + "\n", origin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signing-cert-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, origin = render(args.signing_cert_sha256)
    if args.output.exists() and args.output.is_symlink():
        raise ValueError("unsafe_output_path")
    args.output.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    args.output.write_text(data, encoding="utf-8")
    args.output.chmod(0o644)
    # Public signing certificate identity, never a secret or bearer.
    print("Pinned Watchtower GWAY_WEBAUTHN_ANDROID_ORIGIN=" + origin)
    print("Generated public Digital Asset Links at " + str(args.output))
    print("No service or route has been enabled.")


if __name__ == "__main__":
    main()
