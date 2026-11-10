"""Local deployment authorization using the canonical Ansible inventory.

Inventory describes desired management scope; hostname is independently obtained
from the machine, never from a user-supplied target selector.
"""
import json
from pathlib import Path
import socket
import subprocess

# The CLI is installed as a zipapp, so its ``__file__`` is not a directory
# containing Ansible assets.  The deployment role installs this non-secret
# policy separately at a stable root-owned path.
INVENTORY = Path("/etc/gway-remote/deployment.yml")


def require_local_deployment(repository=None, *, hostname=None, inventory=INVENTORY):
    node = hostname if hostname is not None else socket.gethostname().split(".", 1)[0]
    # Initial release deliberately authorizes local writes only on gway-001.
    # An inventory entry for another node does not enable execution there.
    if node != "gway-001":
        raise RuntimeError("Remote appliance deployment denied on this host")
    try:
        result = subprocess.run(
            ["ansible-inventory", "-i", str(inventory), "--host", node],
            check=True, capture_output=True, text=True, timeout=15,
        )
        vars = json.loads(result.stdout)
        approved = vars.get("remote_managed_repositories")
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Remote deployment inventory unavailable; denied") from exc
    if not isinstance(approved, list) or not approved or not all(isinstance(x, str) for x in approved):
        raise RuntimeError("No approved Remote repositories for this host")
    if repository is not None and repository not in approved:
        raise RuntimeError("Repository is not approved for Remote management on this host")
    # A batch is scoped to approved registered installers, not every known
    # component. Reject inventories that authorize no deployable component.
    if repository is None:
        from .best_effort import INSTALLERS
        if not set(INSTALLERS).intersection(approved):
            raise RuntimeError("No approved appliance deployment targets for this host")
    return tuple(approved)
