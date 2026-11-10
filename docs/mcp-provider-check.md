# Phase B — read-only MCP provider diagnosis (issue #549)

The installed **node-owned** provider manifest remains the only registration authority:
`/etc/gway-mcp-providers/<source_id>.json`. No new provider database,
gateway allowlist, OAuth credential, node identity or service is created.
Every provider continues to own its own MCP tools and `readOnlyHint`/
`destructiveHint` declarations; ambiguous tools require `gway:execute`.

## Local operator usage

On the **node that owns the provider** (not on Watchtower):

```sh
gway-remote mcp provider check odoo --json
gway-remote mcp provider check agentops
```

The command loads the existing trusted manifests through
`discover_installed_providers`, checks the installed executable and fixed
argv using the already deployed parser, performs the provider's bounded stdio
`tools/list` via the existing node provider layer, and reports only sanitized
tool names/required scopes. It **never calls a provider tool**, installs or
activates a release, touches SSH, requests a bearer, or changes a service.

`manifest.revision` means **declared pinned revision**, not confirmed active
release. Likewise, `receipt.state=succeeded` (when a trusted deployment
recipe and readable private historical receipt exist) is **not** proof of
current installed SHA. `installed_release.state=unverified` remains explicit
until an independent installed-release attestation is supported.

## Optional comparison with Watchtower

Use an already authorized **read-only** `mcp_catalog_inspect` MCP call to
obtain its sanitized JSON text. Save **only the diagnostic JSON**, never a
bearer, raw HTTP request or provider arguments. Then on the owning node run:

```sh
gway-remote mcp provider check odoo --watchtower-catalog /tmp/mcp-catalog.json --json
```

The file must be a bounded regular file (not a symlink or device) matching
the `mcp_catalog_inspect` schema. The command compares local
`source_id__tool` names, required scopes and node identity with that
snapshot. `matches_snapshot` or `differs_snapshot` are **comparisons with
caller-provided, unauthenticated input**; they do not assert a fresh,
authenticated Watchtower response. Without the file, state is `unknown`.
The CLI never opens a network connection to Watchtower, accesses secrets,
or extends the MCP public API.

Output is bounded to safe fields: provider, manifest state/declaration SHA,
executable validation state, tool names/scopes, optional comparison status,
deployment recipe presence, historical receipt status, and `unverified`
installed-release SHA. Errors use stable non-sensitive codes; no executable
paths, command arguments, stderr, configuration contents or credentials are
printed. Exit status is 0 for locally available providers without a detected
snapshot mismatch; 1 for unavailable/not installed or differing snapshot;
2 for malformed CLI input or unsafe/unreadable snapshot.

## Catalog parity and deployment boundary

Watchtower now uses a single pure `effective_catalog` composer for
`tools/list` and `mcp_catalog_inspect`. Both use the same backend allowlist,
node federation discovery, local tool ordering and verified OAuth scope
classification. `mcp_source_status`, actual dispatch, scope enforcement
and the SSH transport remain unchanged. Local Watchtower tools retain fixed
`gway:read`/`gway:execute` scopes independent of annotations.

Offline tests verify scope parity (including destructive/ambiguous tools),
collisions, HTTP list/inspect parity, invalid/missing manifests, snapshot
input validation, non-dispatch, old receipt semantics, and unchanged
registrations/permissions. These tests are **not** production proof. Do not
merge/deploy this Draft branch until authorized and CI is accepted.
