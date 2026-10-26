"""Read-only inventory of configured appliance deployment targets."""
from datetime import datetime, timezone
import json
import socket
import subprocess
from .deployment_policy import INVENTORY
from .attempts import read_attempts
from .github_state import GitHub, main_head
from .reconcile import TARGETS
from .status import installed_revision
from .bastion_status import read_bastion_evidence


def _node_policy(node, inventory_path=INVENTORY):
    """Read Ansible inventory without contacting remote hosts."""
    try:
        result = subprocess.run(["ansible-inventory", "-i", str(inventory_path), "--list"],
                                check=True, capture_output=True, text=True, timeout=15)
        hosts = json.loads(result.stdout).get("_meta", {}).get("hostvars", {})
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Ansible inventory unavailable") from exc
    if node not in hosts:
        raise ValueError(f"Unknown inventory node: {node}")
    allowed = hosts[node].get("remote_managed_repositories", [])
    if not isinstance(allowed, list) or any(not isinstance(x, str) for x in allowed):
        raise ValueError("Invalid managed repository allowlist")
    return set(allowed)


def inventory(repository=None, *, node=None, client=None, attempts=None, installed=None, policy=None):
    """Report attempt evidence separately from independently verified installation."""
    names = dict(TARGETS)
    if repository is not None and repository not in names:
        raise ValueError(f"Unknown repository: {repository}")
    local_node = socket.gethostname().split(".", 1)[0]
    node = node or local_node
    local = node == local_node
    allowed = set(policy) if policy is not None else _node_policy(node)
    client = client if client is not None else GitHub()
    attempts = attempts if attempts is not None else (read_attempts() if local else {})
    installed = installed if installed is not None else installed_revision
    rows = []
    for name, source in TARGETS:
        if repository is not None and repository != name:
            continue
        record = attempts.get(name) or {}
        verified = installed(name) if local else None
        latest = main_head(client, source)
        # Release symlinks may expose only 12 characters, unlike GitHub's full SHA.
        relation = ("unknown" if not verified else
                    "current" if latest.lower().startswith(verified.lower()) else "behind")
        release = read_bastion_evidence() if local and name == "gway-bastion" else None
        managed = name in allowed
        deployable = managed and node == "gway-001" and local
        rows.append({"name": name, "repository": source,
                     "installed": "verified" if verified else "unknown",
                     "managed": managed, "deployable": deployable,
                     "management_reason": ("not managed" if not managed else
                                           "remote execution not enabled" if not local else
                                           "only gway-001 can apply" if not deployable else
                                           "approved for local deployment"),
                     "attempted_at": record.get("at"),
                     "attempted_sha": record.get("sha"),
                     "attempt_status": record.get("status", "never-attempted"),
                     "installed_sha": verified,
                     "latest_sha": latest,
                     "revision_status": relation,
                     "release_state": release["release_state"] if release else None,
                     "staged_sha": release["staged_sha"] if release else None})
    return {"node": node, "local_evidence": local, "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": rows}


def format_inventory(report):
    lines = [f'Deployment inventory for {report["node"]} (local evidence: {report["local_evidence"]})',
             f'{"Component":<20} {"Installed":<13} {"Managed":<9} {"Deployable":<11} {"Main":<13} Status']
    for row in report["components"]:
        lines.append(
            f'{row["name"]:<20} {row["installed"]:<13} '
            f'{str(row["managed"]):<9} {str(row["deployable"]):<11} '
            f'{row["latest_sha"][:12]:<13} {row["revision_status"]}'
        )
        if not row["deployable"]:
            lines.append(f'  Reason: {row["management_reason"]}')
    lines.append("Unknown installation is unverified, not absent. Remote nodes are not probed or adopted.")
    return "\n".join(lines)
