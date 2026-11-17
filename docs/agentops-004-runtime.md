# AgentOps #96: explicit node-local Codex runtime

The node-owned MCP provider is registered by its immutable AgentOps release
manifest. GWay Remote reads a **separate**, root-managed
`/etc/gway-mcp-providers/agentops.runtime.json` to prepare the provider's
process environment. This file does not contain authentication material.

A current two-field policy remains valid:

```json
{"workspace":"/absolute/private/owner/workspace","agent_executable":"/absolute/pinned/release/bin/agent"}
```

When Codex is not in `/usr/bin:/bin`, the operator may add exactly one
explicit entry:

```json
{"workspace":"/absolute/private/owner/workspace","agent_executable":"/absolute/pinned/release/bin/agent","codex_executable":"/absolute/owner/managed/bin/codex"}
```

The `codex_executable` value is **not** a command line or a shell expression.
The trusted adapter checks its name, executable target, ownership and containing
directories (root or the executing owner, no group/other writes). An owner
managed executable symlink is supported only after resolution and verification.
Only its containing directory is appended after the pinned AgentOps directory
in the provider PATH. All unknown policy fields fail closed.

## gway-004 acceptance sequence

1. Confirm pinned, attested `gway-004`, owner `arthe`, exact reviewed and
   installed AgentOps and GWay Remote receiver revisions, existing user bus,
   workspace, private admission ledger and no active execution.
2. As the **local installation owner on 004**, explicitly adopt a separate
   private Codex configuration and authentication snapshot from **004 itself**
   with `agent adopt --include-auth` after inspecting the source and target.
   Never copy credentials from 001, from Watchtower or from the gateway.
3. Review and provision a root-owned, non-symlink regular runtime policy
   containing the immutable AgentOps CLI, private workspace and exact local
   Codex executable. Do not install the policy on 001 as a side effect.
4. With the reviewed receiver code active on 004, inspect node-local provider
   discovery and Watchtower's `gway_004_agentops__*` names. Ensure existing
   `agentops__*` names still point only to 001. Verify read-only vs execute
   scopes, wrong-node and unauthorized dispatch denials.
5. Authorize one dedicated read-only test issue and a single frozen UTC
   dispatch only after independent provider identity, private credentials,
   checkout, state ledger, reporting and permissions are proven. Observe the
   terminal report on 004 and absence of any 001 dispatch.

Do not enable scheduler timers or recurring policies on 004. Runtime-policy
installation, receiver deployment, credentials, and live execution are **not**
performed by the code change in this repository.