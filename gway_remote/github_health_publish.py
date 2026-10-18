"""Validate and atomically publish an external hourly watch snapshot.

This tool is a transport boundary: it never runs a watch, GitHub API call,
deployment, or workflow. The watch producer must supply completed evidence.
"""
import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .github_health import MAX_SNAPSHOT_BYTES, REPOSITORIES, read_snapshot


def publish(source, destination):
    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must differ")
    if source.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot exceeds size limit")
    document = json.loads(source.read_bytes())
    if not isinstance(document, dict):
        raise ValueError("Snapshot must be an object")
    # Require a complete watch and preserve lifecycle metadata unchanged.
    completed = datetime.fromisoformat(document["completed_at"].replace("Z", "+00:00"))
    if completed.tzinfo is None:
        raise ValueError("Snapshot timestamp must have timezone")
    if document.get("schema_version") != 1 or document.get("status") != "available":
        raise ValueError("Unsupported snapshot")
    repos = document.get("repositories")
    if (not isinstance(repos, list) or len(repos) != len(REPOSITORIES)
            or any(not isinstance(r, dict) for r in repos)
            or {r.get("name") for r in repos} != set(REPOSITORIES)
            or any(r.get("pass_a_checked") is not True or r.get("pass_b_checked") is not True
                   for r in repos)):
        raise ValueError("Incomplete watch scope")
    alerts = document.get("alerts")
    if (not isinstance(alerts, list) or len(alerts) > 500
            or any(not isinstance(a, dict) or a.get("repository") not in REPOSITORIES
                   or a.get("state") not in ("ACTIVE", "RESOLVED")
                   or not isinstance(a.get("id"), str) or not a["id"] for a in alerts)):
        raise ValueError("Invalid alert records")
    # Validate timestamp freshness using the same reader contract.
    if not (-300 <= (datetime.now(timezone.utc) - completed).total_seconds() <= 7200):
        raise ValueError("Stale or future-dated snapshot")
    payload = json.dumps(document, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot exceeds size limit")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent,
                                         prefix=".github-health-", delete=False) as handle:
            tmp = Path(handle.name)
            os.chmod(tmp, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, destination)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description="Publish completed GitHub health watch snapshot")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    publish(args.source, args.destination)


if __name__ == "__main__":
    main()
