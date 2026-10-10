"""GitHub deployment writer. Requires a separately verified installation."""
from .installed import SHA
from .reconcile import TARGETS

REPOS = dict(TARGETS)


def record_deployment(client, name, sha, verify):
    if name not in REPOS or not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError("invalid deployment revision")
    sha = sha.lower()
    if verify(name, sha) is not True:
        raise RuntimeError("installation not verified")
    repo = REPOS[name]
    existing = client.get(f"repos/{repo}/deployments?environment=gway-001&per_page=100")
    if not isinstance(existing, list):
        raise RuntimeError("invalid deployment response")
    for deployment in existing:
        if deployment.get("sha", "").lower() != sha:
            continue
        statuses = client.get(f"repos/{repo}/deployments/{deployment['id']}/statuses?per_page=100")
        if statuses and statuses[0].get("state") == "success":
            return deployment["id"]
    created = client.post(f"repos/{repo}/deployments", {
        "ref": sha, "environment": "gway-001",
        "auto_merge": False, "required_contexts": [],
    })
    identifier = created.get("id") if isinstance(created, dict) else None
    if not isinstance(identifier, int):
        raise RuntimeError("deployment creation returned no ID")
    if verify(name, sha) is not True:
        raise RuntimeError("installation changed before recording")
    client.post(f"repos/{repo}/deployments/{identifier}/statuses", {
        "state": "success", "description": "Verified installed revision",
    })
    return identifier
