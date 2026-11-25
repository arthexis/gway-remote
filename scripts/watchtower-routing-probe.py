"""Read only the routing variable from the active gateway process."""
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

UNIT = "gway-mcp-gateway.service"
MODES = {"legacy", "canonical-with-aliases", "canonical"}


def probe():
    subprocess.run(["systemctl", "is-active", "--quiet", UNIT], check=True)
    pid = int(subprocess.check_output(["systemctl", "show", UNIT,
                                      "-p", "MainPID", "--value"]))
    if pid <= 1:
        raise ValueError("inactive gateway")
    prefix = b"GWAY_MCP_NODE_ROUTING="
    matches = [x[len(prefix):] for x in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
               if x.startswith(prefix)]
    if len(matches) > 1:
        raise ValueError("ambiguous mode")
    mode = matches[0].decode("ascii") if matches else "legacy"
    if mode not in MODES:
        raise ValueError("unknown mode")
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:19010/mcp", timeout=8):
            raise ValueError("unexpected gateway status")
    except HTTPError as exc:
        if exc.code != 405:
            raise ValueError("gateway health failed") from None
    if int(subprocess.check_output(["systemctl", "show", UNIT,
                                   "-p", "MainPID", "--value"])) != pid:
        raise ValueError("gateway restarted during probe")
    return mode


if __name__ == "__main__":
    try:
        actual = probe()
        if len(sys.argv) > 2 or (len(sys.argv) == 2 and actual != sys.argv[1]):
            raise ValueError("routing mismatch")
    except Exception:
        sys.exit("gateway routing probe failed")
    print(actual)
