# Increment F — source pilot preflight (no activation)

The existing MCP federation requires identical root-owned digest-pinned source
policies on gway-001 and Watchtower. The backend runs as a **user** systemd
service; the gateway runs as a **system** service. Do not use the gateway-only
playbook for the backend.

Before activating any source:

1. Install the repo-owned immutable release independently. Record its exact
   40-character SHA, absolute executable path and non-root runtime account.
2. Prepare an independently reviewed policy with exactly the source's approved
   read-only tool declarations. Do not derive approval from live discovery.
3. Stage policy through the operator-only backend and gateway playbooks.
   Both require explicit approval and digest; they are not part of normal CI
   deployment. Back up both endpoint policies/drop-ins before starting.
4. On the backend, **as the registered service identity**, run
   `python3 scripts/mcp-source-preflight.py --policy /etc/gway-mcp-gateway/sources.json --sha256 <reviewed-policy-digest> --source-id <approved-source-id>`
   from a GWay Remote release with its package importable.
   This checks installed release traversal, identity, exact tool catalog and
   stdio handshake; it does not call business tools.
5. Only after backend preflight succeeds, activate the Watchtower endpoint.
   Validate authenticated `tools/list`, approved `tools/call`, rejection of
   writes, and unchanged built-in GWay tools through the existing connection.
6. Test absent/crashed source isolation. To roll back, restore the previous
   approved policy and drop-in on **both** endpoints, restart each service,
   and verify the namespaced tools disappear. Per-host Ansible rollback is
   not a two-host transaction.

Do not automatically enable Odoo or AgentOps sources. This preflight is
generic and does not read or expose Bastion credentials. Real Odoo queries
require a separate explicitly approved field acceptance step.
