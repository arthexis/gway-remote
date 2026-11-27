#!/usr/bin/env python3
"""Read-only selector for Ansible; same code as standalone bootstrap client."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gway_remote.wireguard_satellite import resolve_executor_user


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", default="")
    parser.add_argument("--override", default="")
    parser.add_argument("--abb-empty-legacy-cutover", action="store_true")
    args = parser.parse_args()
    try:
        if args.abb_empty_legacy_cutover:
            if (args.installer, args.override) != ("ubuntu", "ubuntu"):
                raise PermissionError("ABB identity is fixed")
            from gway_remote.abb_relay_provision import resolve_abb_user
            print(resolve_abb_user(allow_empty_legacy=True))
        else:
            print(resolve_executor_user(args.installer, args.override))
    except (OSError, ValueError, PermissionError) as exc:
        parser.exit(1, "executor provisioning denied: " + type(exc).__name__ + "\n")


if __name__ == "__main__":
    main()
