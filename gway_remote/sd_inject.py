"""Constrained Raspberry Pi Imager cloud-config injector (#682).

This stage only injects the Raspberry Pi Connect first-boot repair. Deferred
Watchtower registration is intentionally NOT represented as complete: it needs
the separate proof-of-possession enrollment API specified by issue #682.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .firstboot_connect import connect_firstboot_script
from .firstboot_deferred import firstboot_claim_source, firstboot_claim_unit, CLIENT_PATH, KEY_PATH, SERVICE

NODE = re.compile(r"gway-[0-9]{3}\Z")


class UnsafeCard(ValueError):
    pass


def _command(*argv: str) -> str:
    return subprocess.check_output(argv, text=True, timeout=10).strip()


def inspect_bootfs(bootfs: Path) -> dict:
    """Fail closed unless a FAT partition of a removable disk is mounted here."""
    if bootfs.is_symlink() or not bootfs.is_dir():
        raise UnsafeCard("bootfs must be an existing physical mount")
    target = str(bootfs.resolve(strict=True))
    try:
        record = json.loads(_command("findmnt", "--json", "-T", target,
                                     "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"))["filesystems"][0]
        if Path(record["target"]).resolve() != Path(target):
            raise UnsafeCard("bootfs must be a mountpoint, not a subdirectory")
        if record["fstype"].lower() not in {"vfat", "fat", "msdos"}:
            raise UnsafeCard("bootfs must be FAT")
        if "rw" not in record["options"].split(","):
            raise UnsafeCard("bootfs is read-only")
        source = record["source"]
        if not source.startswith("/dev/"):
            raise UnsafeCard("unsupported device source")
        block = json.loads(_command("lsblk", "-J", "-o",
                                    "PATH,TYPE,RM,PKNAME,FSTYPE", source))["blockdevices"]
        if len(block) != 1:
            raise UnsafeCard("ambiguous partition")
        part = block[0]
        if part["type"] != "part" or part["fstype"].lower() not in {"vfat", "fat"}:
            raise UnsafeCard("not a FAT partition")
        parent = part.get("pkname")
        if not parent:
            raise UnsafeCard("parent disk unknown")
        disk = json.loads(_command("lsblk", "-dnJ", "-o", "TYPE,RM", "/dev/" + parent))["blockdevices"]
        if len(disk) != 1 or disk[0]["type"] != "disk" or not bool(int(disk[0]["rm"])):
            raise UnsafeCard("disk is not explicitly removable")
        # Reject the running system disk and a card with any other mounted
        # partitions. Never assume a removable root disk is expendable.
        layout = json.loads(_command("lsblk", "-J", "-o", "NAME,MOUNTPOINTS",
                                      "/dev/" + parent))["blockdevices"]
        if len(layout) != 1:
            raise UnsafeCard("ambiguous disk mounts")
        def all_mounts(entry):
            found = list(entry.get("mountpoints") or [])
            for child in entry.get("children") or []:
                found.extend(all_mounts(child))
            return found
        mounts = [m for m in all_mounts(layout[0]) if m]
        if mounts != [target]:
            raise UnsafeCard("card contains other mounted partitions or system mounts")
    except (OSError, KeyError, IndexError, TypeError, ValueError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        if isinstance(exc, UnsafeCard):
            raise
        raise UnsafeCard("unable to verify removable FAT partition") from None
    return {"mount": target, "device": source}


def prepare_cloud_config(raw: str, *, node: str, installer: str,
                         preparation_id: str | None = None,
                         private_key_pem: str | None = None) -> str:
    """Modify existing Imager YAML structurally, retaining all other settings.

    PyYAML is intentionally loaded only here; installations without it fail
    closed rather than attempting fragile text substitutions.
    """
    if not NODE.fullmatch(node):
        raise ValueError("node must match gway-NNN")
    if not raw.startswith("#cloud-config"):
        raise UnsafeCard("not a Raspberry Pi Imager cloud-config")
    try:
        import yaml
        document = yaml.safe_load(raw)
    except (ImportError, Exception) as exc:
        raise UnsafeCard("cloud-config parser unavailable or invalid") from None
    if not isinstance(document, dict):
        raise UnsafeCard("unexpected cloud-config structure")
    if "hostname" in document and document["hostname"] != node:
        raise UnsafeCard("Imager hostname differs from requested node")
    if document.get("gway_sd_inject_v1") is not None:
        raise UnsafeCard("card already injected; revoke prior preparation first")
    sequence = document.get("runcmd", [])
    if not isinstance(sequence, list):
        raise UnsafeCard("unexpected runcmd structure")
    # cloud-init write_files allows a root-only executable to be staged on the
    # target root filesystem; bootfs remains only a transport.
    files = document.get("write_files", [])
    if not isinstance(files, list):
        raise UnsafeCard("unexpected write_files structure")
    script_path = "/usr/local/libexec/gway-connect-firstboot"
    if any(isinstance(entry, dict) and entry.get("path") == script_path for entry in files):
        raise UnsafeCard("first-boot script already present")
    if (preparation_id is None) != (private_key_pem is None):
        raise UnsafeCard("preparation and signing key must be supplied together")
    document["hostname"] = node
    document["write_files"] = files + [{
        "path": script_path, "owner": "root:root", "permissions": "0700",
        "content": connect_firstboot_script(installer),
    }]
    document["runcmd"] = sequence + [[script_path]]
    document["gway_sd_inject_v1"] = {"node": node, "installer": installer,
                                      "connect": "activate"}
    if preparation_id is not None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        try:
            signing_key = load_pem_private_key(private_key_pem.encode("ascii"), password=None)
        except (ValueError, TypeError, UnicodeError):
            raise UnsafeCard("invalid installation signing key") from None
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise UnsafeCard("Ed25519 signing key required")
        client = firstboot_claim_source(node, installer, preparation_id)
        unit_path = "/etc/systemd/system/" + SERVICE
        paths = {entry.get("path") for entry in document["write_files"] if isinstance(entry, dict)}
        if {CLIENT_PATH, KEY_PATH, unit_path} & paths:
            raise UnsafeCard("GWay first-boot files already exist")
        document["write_files"].extend([
            {"path": CLIENT_PATH, "owner": "root:root", "permissions": "0700", "content": client},
            {"path": KEY_PATH, "owner": "root:root", "permissions": "0600", "content": private_key_pem},
            {"path": unit_path, "owner": "root:root", "permissions": "0644",
             "content": firstboot_claim_unit()},
        ])
        packages = document.get("packages", [])
        if not isinstance(packages, list):
            raise UnsafeCard("unsupported cloud-init package format")
        document["packages"] = packages + [pkg for pkg in ("python3-cryptography",)
                                            if pkg not in packages]
        document["runcmd"].extend([["systemctl", "daemon-reload"],
                                    ["systemctl", "enable", SERVICE],
                                    ["systemctl", "start", "--no-block", SERVICE]])
        document["gway_sd_inject_v1"]["preparation_id"] = preparation_id
    result = "#cloud-config\n" + yaml.safe_dump(document, sort_keys=False)
    yaml.safe_load(result)  # validate before any write
    return result


def inject(bootfs: Path, *, node: str, installer: str, commit: bool = False,
           preparation_id: str | None = None, private_key_pem: str | None = None) -> dict:
    location = inspect_bootfs(bootfs)
    file = bootfs / "user-data"
    if file.is_symlink() or not file.is_file():
        raise UnsafeCard("user-data missing or unsafe")
    source = file.read_text(encoding="utf-8")
    prepared = prepare_cloud_config(source, node=node, installer=installer,
                                    preparation_id=preparation_id, private_key_pem=private_key_pem)
    receipt = {"node": node, "device": location["device"],
               "change": "deferred-enrollment-plus-connect" if preparation_id else "connect-firstboot-only",
               "original_sha256": hashlib.sha256(source.encode()).hexdigest(),
               "prepared_sha256": hashlib.sha256(prepared.encode()).hexdigest(),
               "written": False}
    if not commit:
        return receipt
    # FAT rename is not power-loss atomic; snapshot and never claim it is.
    # A protected host-side backup is required for a real write.
    backup = Path(tempfile.mkdtemp(prefix="gway-sd-backup-"))
    os.chmod(backup, 0o700)
    (backup / "user-data").write_text(source, encoding="utf-8")
    os.chmod(backup / "user-data", 0o600)
    staged = bootfs / ".gway-user-data.new"
    if staged.exists() or staged.is_symlink():
        raise UnsafeCard("staging file already exists")
    try:
        with staged.open("x", encoding="utf-8") as stream:
            stream.write(prepared)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, file)
        fd = os.open(str(bootfs), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if staged.exists():
            staged.unlink()
    receipt["written"] = True
    receipt["backup_path"] = str(backup)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject Connect first boot into an Imager SD")
    parser.add_argument("--bootfs", required=True, type=Path)
    parser.add_argument("--node", required=True)
    parser.add_argument("--installer", required=True)
    parser.add_argument("--preparation-id", help="Watchtower preparation ID")
    parser.add_argument("--private-key-file", type=Path, help="root-only Ed25519 PEM file")
    parser.add_argument("--commit", action="store_true",
                        help="write after preflight; default is preview")
    args = parser.parse_args()
    if bool(args.preparation_id) != bool(args.private_key_file):
        parser.error("preparation-id and private-key-file required together")
    signing_key = None
    if args.private_key_file:
        if args.private_key_file.is_symlink() or (args.private_key_file.stat().st_mode & 0o077):
            parser.error("private-key-file must not be a symlink or group/world readable")
        signing_key = args.private_key_file.read_text(encoding="ascii")
    print(json.dumps(inject(args.bootfs, node=args.node,
                            installer=args.installer, commit=args.commit,
                            preparation_id=args.preparation_id, private_key_pem=signing_key),
                     sort_keys=True))


if __name__ == "__main__":
    main()
