# Federated MCP lifecycle refactor (#487): increment A

## Current ownership boundaries

| Responsibility | Implementation | Observable behavior |
| --- | --- | --- |
| Installed provider discovery | node: `mcp_installed_providers.py` | Root-owned safe manifests; policy `agentops.runtime.json` excluded |
| Catalog and invocation | node: `mcp_node_providers.py`, `mcp_source_stdio.py` | Node-owned tool classification; per-provider failures isolated; call revalidates declaration |
| Effective tool aggregation | Watchtower: `mcp_bearer_gateway.py`, federation | `tools/list` advertises effective dynamic catalog; `mcp_catalog_inspect` projects origins/scopes |
| Authorization | bearer gateway + trusted node scope | `gway:read` / `gway:execute`; client payload cannot upgrade authorization |
| Transport | existing authenticated node transport | No new transport or provider-side execution on Watchtower |
| Packaging | provider-owned installer + Ansible | Atomic safe manifests; rollback and idempotence regression from #474 |

## Findings and decisions

1. `mcp_catalog_inspect` independently reconstructs upstream filtering and local ordering, risking drift from `tools/list`. Increment C should extract a shared effective-catalog helper only after parity tests.
2. Manifest parser rejects invalid JSON globally: fail-closed behavior is secure, but diagnostics need characterization before changes. Policy files must not be interpreted as manifests (#486).
3. `provider_list` and `provider_call` both discover catalog intentionally; preserve call-time revalidation against stale/changed tools.
4. Avoid fixed tool counts, hardcoded releases, per-tool Watchtower approval, new repositories, or changes to OAuth and transport.

## Follow-on PR gates

- **B/C:** Versioned manifest/release contract and shared classification/error handling, backward-compatible with existing providers; tests for unsafe files, rollback, scope denial and catalog parity.
- **D/E:** Consolidate fixtures and contracts; verify Ansible render, systemd, release and second deployment `changed=0`; safe read-only E2E only after CI.

## Migration, risks and rollback

Increment A contains documentation and characterization tests only: no runtime behavior, migration, service restart or production deployment. Later PRs must preserve existing manifest compatibility and rollback atomically to the prior release. Never write Odoo/AgentOps production data during acceptance.
