#!/usr/bin/env python3
"""Retired migration entrypoint. Provider-owned manifests must never be rewritten.

The former one-time migration read /etc/gway-mcp-gateway/sources.json and
replaced /etc/gway-mcp-providers/<source_id>.json on every GWay Remote deploy.
That could silently downgrade the installed Odoo provider, and it also
published/deleted an AgentOps-owned manifest. These are no longer Remote's
responsibilities: each provider installs its own root-owned manifest, while
Remote validates and discovers it using mcp_installed_providers.

Deliberately fail closed if invoked by an out-of-date caller. The reviewed
Ansible playbook no longer invokes this utility. No migration, deletion,
publication, chmod, or directory creation is performed here.
"""


def main():
    raise SystemExit(
        "MCP manifest convergence is retired; use the provider-owned installer"
    )


if __name__ == "__main__":
    main()
