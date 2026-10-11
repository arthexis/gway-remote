# Codex task queue — Chunk 2A

The public CLI is now `gway-remote codex`; `codex-worker` remains a
compatibility alias for the installed user service and older scripts.

Read-only inspection:
- `gway-remote codex status` — existing idle worker socket
- `gway-remote codex tasks` — locally persisted tasks
- `gway-remote codex task ID` — one task by ID

The task ledger is stored at `~/.local/state/gway-remote/codex-tasks.sqlite3`
(mode 0600). It supports requested → queued → running → terminal
(succeeded/failed/cancelled), plus interrupted-on-restart. A partial unique
index prevents two simultaneous `running` rows, including across DB
connections. All transitions compare the expected state atomically.

**Part A is intentionally non-executing.** There is no public task submission,
approval, execution, or cancellation command yet. The queue API is internal
until Part B introduces authenticated admission and Part C adds subprocess
management. No new services, background polling, or satellite workers.

The service's existing `codex-worker` invocation remains valid. Tests use
temporary databases and do not touch the installed worker or live services.
