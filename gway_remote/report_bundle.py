"""Create an artifact-safe report bundle from local appliance state."""
import json
from pathlib import Path
import re

from .attempts import DEFAULT_DIR
from .logs import export_log, sanitize
from .status import status

_VALID_LOG = re.compile(r"[0-9]{8}T[0-9]{12}[0-9]{6}Z-[a-z0-9-]+-[0-9a-f]{12}\.log")


def bundle(destination, directory=DEFAULT_DIR, probe=None):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    report = status(directory, probe=probe) if probe is not None else status(directory)
    public = {**report, "components": []}
    logs = destination / "logs"
    logs.mkdir(exist_ok=True)
    for component in report["components"]:
        entry = dict(component)
        if entry.get("error"):
            entry["error"] = sanitize(str(entry["error"]))[:500]
        name = entry["name"]
        filename = entry.get("log")
        if filename and _VALID_LOG.fullmatch(filename):
            source = Path(directory) / "logs" / filename
            if source.is_file() and not source.is_symlink():
                export_log(source, logs / filename)
        public["components"].append(entry)
    (destination / "status.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    (destination / "summary.json").write_text(json.dumps({
        "schema": "gway-remote/report/v1", "node": public["node"],
        "checked_at": public["checked_at"],
        "components": public["components"],
    }, indent=2) + "\n", encoding="utf-8")
    lines = ["## Gway Remote appliance report", "",
             "| Component | Attempted SHA | Installation | Health | Log |",
             "| --- | --- | --- | --- | --- |"]
    for item in public["components"]:
        sha = (item["attempted_sha"] or "unknown")[:12]
        log = item.get("log")
        log_label = "included" if log and (logs / log).exists() else "none"
        lines.append(f'| {item["name"]} | {sha} | {item["installation"]} | '
                     f'{item["health"]} | {log_label} |')
    lines.extend(["", "Last attempted SHA does not prove the installed revision.",
                  "Download the workflow artifact for sanitized installation logs.", ""])
    markdown = "\n".join(lines)
    (destination / "summary.md").write_text(markdown, encoding="utf-8")
    return markdown
