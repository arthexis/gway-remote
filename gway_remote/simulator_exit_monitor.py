"""Run one simulator and persist its exit code for later inspection."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


def main():
    directory = Path(sys.argv[1])
    run_id = sys.argv[2]
    child = subprocess.Popen(sys.argv[3:], stdin=subprocess.DEVNULL)

    def terminate(signum, frame):
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGTERM, terminate)
    code = child.wait()
    temp = directory / ("exit-" + run_id + ".tmp")
    temp.write_text(json.dumps({"exit_code": code}))
    os.replace(temp, directory / ("exit-" + run_id + ".json"))


if __name__ == "__main__":
    main()
