"""Read-only Watchtower inspection entrypoint."""
import json
from pathlib import Path
from .watchtower_enrollment import Ledger


def main():
    settings = json.loads(Path("/etc/gway-remote/watchtower.json").read_text())
    ledger = Ledger(Path(settings["ledger"]), network=settings["network"], gateway=settings["gateway"])
    print(json.dumps(ledger.inspection_snapshot(), sort_keys=True))


if __name__ == "__main__":
    main()
