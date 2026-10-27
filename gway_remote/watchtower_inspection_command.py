"""Restricted Watchtower snapshot export; never initialize or modify enrollment."""
import json
import os
from pathlib import Path

from .node_inspection import snapshot_from_path


def main():
    # Forced-command SSH must reject all but the explicitly requested operation.
    if os.environ.get("SSH_ORIGINAL_COMMAND") != "snapshot":
        raise SystemExit("inspection operation denied")
    settings = json.loads(Path("/etc/gway-remote/watchtower.json").read_text())
    print(json.dumps(snapshot_from_path(Path(settings["ledger"])), sort_keys=True))


if __name__ == "__main__":
    main()
