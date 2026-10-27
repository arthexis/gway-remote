"""Read-only, fixed allowlist of installed revision evidence on satellites."""
import re
import subprocess

RELEASES = {
    "ocpp-csms": ".local/share/ocpp-csms/current",
    "ocpp-reports": ".local/share/ocpp-reports/current",
}
REVISION = re.compile(r"(?<![0-9a-f])([0-9a-f]{40}|[0-9a-f]{12})(?:-dev)?(?![0-9a-f])")


def inspect_revisions(node, config, *, runner=subprocess.run):
    """Report evidence only; never guess installation from a missing link."""
    rows = []
    for name, release in RELEASES.items():
        sha = None
        try:
            result = runner(
                ["ssh", "-F", str(config), "-o", "BatchMode=yes",
                 "-o", "StrictHostKeyChecking=yes", node,
                 "readlink", "-f", release],
                capture_output=True, text=True, check=True, timeout=15,
            )
            if len(result.stdout) <= 4096:
                target = result.stdout.strip()
                if "/releases/" in target:
                    candidate = target.rsplit("/releases/", 1)[1].split("/", 1)[0]
                    match = REVISION.fullmatch(candidate)
                    if match:
                        sha = match.group(1)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        rows.append({"component": name, "installed_sha": sha,
                     "evidence": "release-symlink" if sha else "unknown"})
    return rows
