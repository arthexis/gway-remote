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
    args = parser.parse_args()
    try:
        print(resolve_executor_user(args.installer, args.override))
    except (OSError, ValueError, PermissionError) as exc:
        parser.exit(1, "executor provisioning denied: " + type(exc).__name__ + "\n")


if __name__ == "__main__":
    main()
