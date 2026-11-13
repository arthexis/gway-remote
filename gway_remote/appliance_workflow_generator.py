"""P2 offline-only static Appliance Deploy generator; no authority to deploy.

Only the pre-approved dispatcher subset of validated P1 catalog entries can be
rendered. Installed inventory, MCP manifests and runtime policy stay separate.
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import sys

from .catalog_shadow import check_shadow_parity, load_catalog
from .deploy_dispatch import TARGETS as DISPATCH_TARGETS
from .deploy_failure_issues import REPOSITORIES

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_WORKFLOW = ROOT / ".github" / "workflows" / "appliance-deploy.yml"

# Deliberately *not* read from the seven-item catalog or from Ansible.
# This is a separately reviewed fixed admission policy, six targets on main.
# Reports needs an independently approved #564 before changing this tuple.
TRACKS = (
    ("ocpp-csms",),
    ("gway-lcd-sound", "gway-agent-ops", "gway-ap-kiosk",
     "gway-rfid", "gway-bastion"),
)
TEMPLATES = {
    "skeleton": "appliance-deploy.skeleton.yml.in",
    "first": "appliance-deploy.first.yml.in",
    "linked": "appliance-deploy.linked.yml.in",
    "bastion": "appliance-deploy.bastion.yml.in",
}
MARKERS = ("@@CHOICES@@", "@@DEPLOY_JOBS@@", "@@REPORT_NEEDS@@",
           "@@REPORT_MAP@@")


def _job_id(name: str) -> str:
    return name.replace("-", "_")


def _substitute_once(source: str, token: str, value: str) -> str:
    if source.count(token) != 1:
        raise ValueError(f"missing or duplicate trusted template slot {token}")
    return source.replace(token, value, 1)


def _load_templates(directory: Path) -> dict[str, str]:
    # Every filename is fixed in reviewed Python, never taken from JSON.
    contents = {}
    for key, name in TEMPLATES.items():
        value = (directory / name).read_text(encoding="utf-8")
        if not value.endswith("\n") or "\r" in value:
            raise ValueError(f"noncanonical {key} template")
        contents[key] = value
    skeleton = contents["skeleton"]
    for token in MARKERS:
        if skeleton.count(token) != 1:
            raise ValueError(f"unexpected skeleton slot {token}")
    for key in ("first", "linked", "bastion"):
        template = contents[key]
        if template.count("@@JOB@@") < 1 or template.count("@@TARGET@@") < 1:
            raise ValueError(f"missing mandatory job slot in {key}")
        if key == "first" and "@@PREV@@" in template:
            raise ValueError("root job unexpectedly depends on another job")
        if key != "first" and template.count("@@PREV@@") != 1:
            raise ValueError(f"invalid dependency slot in {key}")
        if any(marker in template for marker in MARKERS):
            raise ValueError("top-level slot embedded inside job template")
    return contents


def _job(template: str, name: str, predecessor: str | None) -> str:
    # Canonical name/job-ID grammar already checked by the P1 loader.
    result = template.replace("@@TARGET@@", name).replace("@@JOB@@", _job_id(name))
    if predecessor is not None:
        result = result.replace("@@PREV@@", _job_id(predecessor))
    if "@@" in result:
        raise ValueError("unresolved job template marker")
    return result


def render_workflow(*, catalog=None, template_dir=None) -> str:
    """Return static YAML in memory; does not modify checkout, inventory or host."""
    catalog = load_catalog() if catalog is None else check_shadow_parity(catalog)
    targets = {target.id: target for target in catalog.targets}
    names = tuple(name for track in TRACKS for name in track)
    if len(names) != len(set(names)) or not all(TRACKS):
        raise ValueError("invalid or duplicated generator track")
    if ("all", *names) != DISPATCH_TARGETS:
        raise ValueError("reviewed generator tracks differ from dispatcher")
    expected_reporters = {_job_id(name): name for name in names}
    if dict(REPOSITORIES) != expected_reporters or tuple(REPOSITORIES) != tuple(expected_reporters):
        raise ValueError("failure reporter job map differs from the dispatcher")
    if any(name not in targets for name in names):
        raise ValueError("unrecognized generator target")
    if "ocpp-reports" in names or "ocpp-simulator" in names:
        raise ValueError("unadmitted target in generator policy")
    if targets["gway-bastion"].release_mode != "stage_only":
        raise ValueError("Bastion must remain stage_only")
    templates = _load_templates(Path(template_dir) if template_dir is not None else TEMPLATE_DIR)

    blocks = []
    for track in TRACKS:
        for index, name in enumerate(track):
            predecessor = track[index - 1] if index else None
            kind = ("bastion" if name == "gway-bastion" else
                    "first" if index == 0 else "linked")
            if kind == "bastion" and predecessor is None:
                raise ValueError("Bastion must have a reviewed predecessor")
            blocks.append(_job(templates[kind], name, predecessor))
    mapping = "".join(f'              "{_job_id(name)}": "{name}",\n' for name in names)
    slots = {
        "@@CHOICES@@": "".join(f"          - {name}\n" for name in ("all", *names)).rstrip("\n"),
        "@@DEPLOY_JOBS@@": "".join(blocks),
        "@@REPORT_NEEDS@@": "[admission, " + ", ".join(_job_id(name) for name in names) + "]",
        "@@REPORT_MAP@@": mapping.rstrip("\n"),
    }
    result = templates["skeleton"]
    for token, value in slots.items():
        result = _substitute_once(result, token, value)
    if "@@" in result:
        raise ValueError("unresolved workflow template marker")
    return result


def check_workflow(path=None, *, catalog=None, template_dir=None) -> bool:
    """Byte comparison only. No writes, runs, dispatches or deployment calls."""
    source = render_workflow(catalog=catalog, template_dir=template_dir)
    filename = Path(path) if path is not None else DEFAULT_WORKFLOW
    return filename.read_bytes() == source.encode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate/check reviewed Appliance Deploy YAML offline")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true",
                         help="Fail on byte drift; never update files")
    actions.add_argument("--render", action="store_true",
                         help="Print deterministic YAML to stdout; never update files")
    args = parser.parse_args(argv)
    expected = render_workflow()
    if args.render:
        sys.stdout.write(expected)
        return 0
    actual = DEFAULT_WORKFLOW.read_bytes()
    if actual == expected.encode("utf-8"):
        print("Appliance Deploy YAML matches reviewed P2 generator byte-for-byte")
        return 0
    sys.stderr.write("Appliance Deploy YAML differs from checked-in generator output\n")
    original = actual.decode("utf-8", errors="replace").splitlines(keepends=True)
    generated = expected.splitlines(keepends=True)
    for line in list(difflib.unified_diff(original, generated,
                                          fromfile="committed YAML",
                                          tofile="generated YAML"))[:120]:
        sys.stderr.write(line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
