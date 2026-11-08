"""Local read-only Ansible entrypoint for the existing deployment evidence v1.

No independent probe implementation: status/health own observations and the
existing adapter owns normalization.  No deployment permissions are granted.
"""
import argparse
import json
import socket

from .deployment_evidence import validate
from .deployments import _node_policy
from .reconcile import TARGETS
from .status import status


def observe(component, *, allowed, report=None):
    """Select one authorized local component from the existing status report."""
    repository = dict(TARGETS).get(component)
    if repository is None or repository not in allowed:
        raise ValueError("component is not authorized for observation")
    if report is None:
        report = status(depth="deep")
    matches = [row for row in report["components"] if row.get("name") == component]
    if len(matches) != 1:
        raise ValueError("component evidence unavailable or ambiguous")
    return validate(matches[0]["deployment_evidence"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Observe existing local deployment evidence")
    parser.add_argument("--component", required=True, choices=sorted(dict(TARGETS)))
    args = parser.parse_args(argv)
    # The existing inventory is the authority for managed components.
    # Unlike deployment, observation never invokes installers or remote SSH.
    node = socket.gethostname().split(".", 1)[0]
    allowed = _node_policy(node)
    print(json.dumps(observe(args.component, allowed=allowed), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
