# Codex GitHub discovery

The existing idle Codex worker checks approved repositories every 300 seconds when `GITHUB_TOKEN` is present in its service environment. `GWAY_CODEX_POLL_SECONDS` may increase this interval (minimum 60 seconds). No second daemon is created. The worker remains execution-disabled.

Only open issues with the `local-agent` label, created by GitHub user `arthexis` (numeric account ID `780437`), are imported as `requested` tasks. Issues from other accounts and pull requests are ignored. Discovery does not approve or execute tasks.

Manual inspection: `gway-remote codex discover`, `gway-remote codex tasks`, `gway-remote codex task ID`.

To reject: `gway-remote codex veto ID --reason 'Not for local execution'`. A veto persists across restarts and discovery passes. To lift it: `gway-remote codex unveto ID`; this returns to `requested` and does not approve execution.

Do not enable the worker in production until CI, migration, credential handling, and local field validation pass. A read-only GitHub token should be provisioned via a protected service environment, never committed to the repository. Closed-issue reconciliation remains a separate hardening requirement.
