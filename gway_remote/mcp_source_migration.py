"""Convert a pinned legacy MCP policy to node-owned discovery (v2).

This is an offline migration helper. It does not change the live policy or
restart services. Operators must stage and verify the resulting file through
Ansible, on the owning node only.
"""
import argparse
import json
from pathlib import Path


def migrate_policy(data):
    if type(data) is not dict or set(data) != {"version", "sources"}:
        raise ValueError("invalid source policy")
    if data["version"] not in (1, 2) or type(data["sources"]) is not list:
        raise ValueError("unsupported source policy")
    migrated = []
    for entry in data["sources"]:
        if type(entry) is not dict:
            raise ValueError("invalid source entry")
        if data["version"] == 1:
            if set(entry) != {"registration", "tools"} or type(entry["tools"]) is not list:
                raise ValueError("invalid legacy source entry")
        elif set(entry) != {"registration"}:
            raise ValueError("invalid source entry")
        registration = entry["registration"]
        if type(registration) is not dict:
            raise ValueError("invalid registration")
        migrated.append({"registration": dict(registration)})
    return {"version": 2, "sources": migrated}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    if args.source.resolve() == args.destination.resolve():
        parser.error("in-place migration is forbidden")
    migrated = migrate_policy(json.loads(args.source.read_text()))
    if args.destination.exists():
        parser.error("destination exists; refusing overwrite")
    args.destination.write_text(json.dumps(migrated, indent=2, sort_keys=True) + "\n")
    args.destination.chmod(0o600)


if __name__ == "__main__":
    main()
