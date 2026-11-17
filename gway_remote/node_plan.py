"""Read-only comparison of node policy with the reviewed deployment catalog."""
import json
import subprocess

from .deployment_policy import INVENTORY
from .target_export import export_targets


def plan(node, *, inventory=INVENTORY, hostvars=None, catalog=None):
    if hostvars is None:
        try:
            result = subprocess.run(['ansible-inventory', '-i', str(inventory), '--list'],
                                    check=True, capture_output=True, text=True, timeout=15)
            hostvars = json.loads(result.stdout)['_meta']['hostvars']
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('inventory unavailable') from exc
    if not isinstance(hostvars, dict) or node not in hostvars or not isinstance(hostvars[node], dict):
        raise ValueError('unknown inventory node')
    host = hostvars[node]
    managed = host.get('remote_managed_repositories', [])
    agent = host.get('gway_agent_allowed_repos', [])
    for value in (managed, agent):
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError('invalid repository policy')
    catalog = catalog if catalog is not None else export_targets()
    targets = catalog['targets']
    mapping = {row['name']: row['repository'] for row in targets}
    known_agent = set(mapping.values()) | {'arthexis/gway-remote'}
    suggested = sorted({mapping[name] for name in managed if name in mapping})
    return {'schema': 'gway-remote/node-plan/v1', 'node': node,
            'catalog_revision': catalog['revision'],
            'managed_repositories': managed, 'agent_configured_repositories': agent,
            'suggested_agent_repositories': suggested,
            'suggested_agent_additions': sorted(set(suggested) - set(agent)),
            'unknown_managed_repositories': sorted(set(managed) - set(mapping)),
            'unknown_agent_repositories': sorted(set(agent) - known_agent),
            'duplicate_managed_repositories': sorted({x for x in managed if managed.count(x) > 1}),
            'duplicate_agent_repositories': sorted({x for x in agent if agent.count(x) > 1}),
            'evidence': 'inventory only; no remote host, runtime, enrollment or provider was inspected',
            'note': 'Suggestions grant no permissions; Agent Ops admission follows its installed version and policy.'}


def format_plan(report):
    return '\n'.join([f"Node plan: {report['node']}",
        f"Catalog revision: {report['catalog_revision']}",
        *(f"{key}: {', '.join(report[key]) or '(none)'}" for key in (
            'managed_repositories', 'agent_configured_repositories', 'suggested_agent_additions',
            'unknown_managed_repositories', 'unknown_agent_repositories',
            'duplicate_managed_repositories', 'duplicate_agent_repositories')),
        report['evidence'], report['note']])
