"""Isolated CI fixture: reuse real inventory authorization and v1 adapter.

Activated only when GWAY_OBSERVE_E2E=1. Never installed or deployed.
"""
import os

if os.environ.get("GWAY_OBSERVE_E2E") == "1":
    from gway_remote import deployments, status
    from gway_remote.deployment_evidence import adapt_component

    _real_policy = deployments._node_policy

    def _isolated_policy(node):
        return _real_policy(node, inventory_path=os.environ["GWAY_OBSERVE_INVENTORY"])

    def _fixture_status(*, depth="deep"):
        row = {"name": "gway-lcd-sound", "installed_sha": None,
               "health": "unknown"}
        row["deployment_evidence"] = adapt_component(
            row, observed_at="2026-11-08T00:00:00+00:00", depth=depth)
        return {"components": [row]}

    deployments._node_policy = _isolated_policy
    status.status = _fixture_status
