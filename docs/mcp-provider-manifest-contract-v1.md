# Node-owned MCP manifest contract (v1)

This documents the **existing** backward-compatible on-disk contract. `MANIFEST_SCHEMA_VERSION=1` is a parser constant; v1 manifests have no `schema` key. Introducing a new key requires a separate migration.

- Installation directory `/etc/gway-mcp-providers` is root-owned, not group/other writable, and never symlinked. Only `<source_id>.json` manifests are read. `agentops.runtime.json` is policy, not a provider.
- Root-owned manifest is a regular non-symlink file, maximum 8192 bytes, not group/other writable. Exact fields: `source_id`, `revision`, `executable`, `argv`. Unknown fields fail closed.
- Source ID matches filename and registry syntax; revision is a full 40-character lowercase hex SHA. Executable is an absolute normalized non-symlink regular file, executable but not group/other writable. Fixed argv starts with executable.
- Installer must create immutable release first, publish a complete correctly owned temporary manifest, and atomically rename it. Rollback atomically restores prior manifest pointing at prior release. Identical content and permissions must yield Ansible `changed=0` on second run.
- Provider owns tool declarations. Read requires explicit safe MCP annotations; ambiguous/destructive tools require execute. Watchtower enforces bearer scopes and routes over authenticated transport, without a per-tool approval registry.
- Invalid manifests fail closed; runtime provider failures return typed non-secret codes. Never disclose paths, tokens, stderr or command arguments in public errors.

#474/PR #488 validates isolated Ansible convergence, rollback and missing/timeout errors. #487 D+E will expand rendered deployment and release checks.
