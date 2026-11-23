"""Create a per-card Ed25519 key; output public key only (#682).

Run on gway-001 as the installer operator. Never reuse a key for another SD.
"""
import argparse
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, NoEncryption,
)


def generate(path: Path) -> str:
    if path.is_symlink() or not path.parent.is_dir():
        raise ValueError("unsafe key output path")
    private = Ed25519PrivateKey.generate()
    key = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8,
                                NoEncryption())
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(key)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.urlsafe_b64encode(public).decode("ascii").rstrip("=")


def main():
    parser = argparse.ArgumentParser(description="Issue a fresh private key for one SD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(generate(args.output))


if __name__ == "__main__":
    main()
