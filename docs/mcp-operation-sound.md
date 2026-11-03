# MCP node execution audio

The GWay Remote bounded node executor (issue #317 Increment B) can publish
best-effort local audio through `McpOperationSound(node, request_id)`. This
module is **prepared but not wired** until the authorized node executor exists.
Current MCP read-only tools must stay silent.

Call `notify("mcp-exec-started")` only after exact target identity,
capabilities, scope, and approval are validated and the executor actually
begins. On the terminal result, call exactly one of:

| Event | LCD Sound mapping | Meaning |
| --- | --- | --- |
| `mcp-exec-started` | busy | Admitted execution began |
| `mcp-exec-completed` | ok | Command exited successfully |
| `mcp-exec-failed` | error | Command exited nonzero or executor failed |
| `mcp-exec-timed-out` | warning | Bounded execution timed out |

Use the request ID from the authorized executor (never untrusted raw shell
text). Never notify on `node_list`, `node_capabilities`, previews, rejected
requests, or Watchtower relay activity. Audio runs **on the target node**, not
Watchtower, and never substitutes for audited structured results.

The player uses the existing `gway-remote` source motif and respects user
sound mappings, mute state, and cooldown. Existing event mappings are inserted
only when absent, preserving custom mappings. Sound failure, SQLite failure,
timeout and missing player are swallowed; playback has a 3-second timeout and
cannot change command outcomes. A local SQLite receipt deduplicates by
(request, node, event) for seven days; retries with a new request ID may sound
again. No arguments, command output, credentials or IP addresses are passed
to the player or stored in receipts.

`GWAY_REMOTE_SOUND_DISABLE=1` suppresses all remote-operation audio.
Deploy updated `gway-lcd-sound` mapping before expecting playback; older
players silently ignore unknown events.
