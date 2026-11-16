"""MaintenanceFence V1-D0 static OFFLINE entrypoint inventory, never admission.

Catalog evidence is limited to audited source anchors. Presence of an anchor
does NOT certify that all side effects or external AgentOps paths are covered.
No entrypoint imports this module, and no effect is performed here.
"""
from dataclasses import dataclass
from pathlib import PurePosixPath

from .maintenance_fence_resources import conflicts, plan

VERSION = "v1-d0"
LOCK_ORDER = ("github_queue", "node_coordinator", "sqlite_transaction",
              "legacy_flock", "side_effect")
EXPECTED_ROUTES = frozenset({
    "appliance_workflow", "backend_push", "simulator_schedule",
    "github_dispatch", "provider_broker", "provider_worker",
    "node_exec_worker", "watchtower_manual_ledger", "agentops_federated",
})
# Global root overlaps child operations; conservative by design until the
# real footprint of each route can be verified.
_NODE = "node/gway-001"
_SIM = "node/gway-001/deploy/ocpp-simulator"
_PROVIDER = "node/gway-001/deploy/gway-remote"


class InventoryError(ValueError):
    def __init__(self):
        super().__init__("invalid_maintenance_effect_inventory_v1d0")


@dataclass(frozen=True)
class EffectRoute:
    route_id: str
    source: str
    anchor: str
    effect_boundary: str
    resources: tuple[str, ...]
    existing_guard: str
    visibility: str
    notes: str


ROUTES = (
    EffectRoute("appliance_workflow", ".github/workflows/appliance-deploy.yml",
                "concurrency:", "workflow_dispatch / Ansible jobs",
                (_NODE,), "github:gway-001-appliance", "local_source",
                "Workflow admits other nodes: not yet covered by gway-001-only planner"),
    EffectRoute("backend_push", ".github/workflows/deploy-backend.yml",
                "concurrency:", "push main / deploy.sh and Watchtower Ansible",
                (_NODE,), "github:gway-001-appliance-report", "local_source",
                "Watchtower is a distinct node and is not fenced by this resource"),
    EffectRoute("simulator_schedule", ".github/workflows/ocpp-simulator-deploy.yml",
                "ocpp-simulator-gway-001-auto-install", "scheduled local installer",
                (_SIM,), "github:ocpp-simulator-gway-001-auto-install",
                "local_source", "External simulator deploy.sh flock is not inventoried here"),
    EffectRoute("github_dispatch", "gway_remote/deploy_dispatch.py",
                "workflow_run_id", "GitHub workflow_dispatch POST",
                (_NODE,), "github:downstream-workflow-only", "local_source",
                "Dispatch accepted is not proof of execution or node lock"),
    EffectRoute("provider_broker", "gway_remote/mcp_deployment_broker.py",
                "LOCK_NAME = \".managed-provider.lock\"",
                "subprocess.run declaration runner", (_PROVIDER,),
                "flock:.managed-provider.lock", "local_source",
                "Provider lock is not a fleet lock"),
    EffectRoute("provider_worker", "gway_remote/mcp_deployment_broker.py",
                "def worker(application, request_id", "worker invokes broker run",
                (_PROVIDER,), "flock:per-request+provider", "local_source",
                "Worker request lock and provider lock have distinct meanings"),
    EffectRoute("node_exec_worker", "gway_remote/node_exec_worker.py",
                'subprocess.Popen(["/bin/sh", "-c", row["command"]]',
                "generic subprocess spawn", (_NODE,),
                "request-ledger:node-exec", "local_source",
                "Arbitrary allowed commands require conservative whole-node footprint"),
    EffectRoute("watchtower_manual_ledger", "gway_remote/manual_deploy_broker.py",
                "class DeploymentReceipts:", "manual deployment ledger only",
                (_NODE,), "sqlite:manual-ledger", "local_source",
                "The executing service is separate; this ledger is not a real lock"),
    EffectRoute("agentops_federated", "EXTERNAL:arthexis/gway-agent-ops",
                "", "AgentOps submit / external executor", (_NODE,),
                "external:unverified", "external_unverified",
                "No local source anchor proves AgentOps runtime or quiescence"),
)


def validate_catalog(routes=ROUTES):
    """Fail closed if known paths, anchors, resources or coverage are missing."""
    if type(routes) not in (tuple, list):
        raise InventoryError()
    ids = [r.route_id for r in routes if type(r) is EffectRoute]
    if len(ids) != len(routes) or len(set(ids)) != len(ids) or set(ids) != EXPECTED_ROUTES:
        raise InventoryError()
    for route in routes:
        if not route.effect_boundary or not route.existing_guard or not route.notes:
            raise InventoryError()
        if route.visibility == "local_source":
            p = PurePosixPath(route.source)
            if (route.source.startswith("/") or ".." in p.parts or
                    not route.anchor or not route.source or
                    p.suffix not in (".py", ".yml")):
                raise InventoryError()
        elif route.visibility != "external_unverified" or not route.source.startswith("EXTERNAL:") or route.anchor:
            raise InventoryError()
        try:
            canonical = plan(route.resources)
        except ValueError:
            raise InventoryError() from None
        if (canonical.resources != route.resources
                or any(resource.split("/")[1] != "gway-001"
                       for resource in route.resources)):
            raise InventoryError()
    return tuple(routes)


def possible_conflicts(left, right):
    """Conservative source-level conflict indication, never a live lock."""
    if type(left) is not EffectRoute or type(right) is not EffectRoute:
        raise InventoryError()
    return conflicts(plan(left.resources), plan(right.resources))


def validate_lock_sequence(phases):
    """Proposed ordering only; sqlite transactions must never span subprocesses."""
    if type(phases) not in (tuple, list) or len(set(phases)) != len(phases):
        raise InventoryError()
    if any(type(p) is not str or p not in LOCK_ORDER for p in phases):
        raise InventoryError()
    if list(phases) != sorted(phases, key=LOCK_ORDER.index):
        raise InventoryError()
    return tuple(phases)


def audit_local_source_anchors(routes, read_text):
    """Offline snapshot consistency against audited source text, not completeness.

    read_text is injected for hermetic testing; no repository or node I/O here.
    """
    validate_catalog(routes)
    checked = []
    for route in routes:
        if route.visibility == "external_unverified":
            continue
        raw = read_text(route.source)
        if type(raw) is not str or route.anchor not in raw:
            raise InventoryError()
        checked.append(route.route_id)
    return tuple(checked)
