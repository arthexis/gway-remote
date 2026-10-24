# M2b — GitHub Actions read-only MCP inspection

This implementation adds exactly three read-only MCP tools:
- `github_workflow_runs(repository?, branch?, status?, event?, limit?)`
- `github_workflow_status(repository, run_id)`
- `github_workflow_errors(repository, run_id, job_id?, limit?)`

The adapter uses GitHub REST `GET` APIs only. Its repository allowlist is
derived from `target_export.export_targets()`, matching Gway Remote's
canonical deployment targets. No separate allowlist or mutable Actions
operations are introduced.

## Credential and operations

Provision a distinct short-lived fine-grained GitHub credential with
**Actions: Read** and **Metadata: Read** for the approved repositories.
Supply it to the MCP service as `GWAY_MCP_GITHUB_TOKEN` using a protected
service environment file or secret manager, never Git, ChatGPT text, CLI
arguments or URLs. Restrict ownership/mode and rotate in the same protected
mechanism. This is **not** `GWAY_MCP_BEARER_TOKEN` (MCP transport
authentication), nor the mobile API token.

The MCP HTTP listener stays bound to `127.0.0.1:8770` and remains
inactive until the separately approved OAuth/tunnel and service rollout.
Do not expose GitHub issue data through an anonymous gateway.

## Behavior and limitations

- Live GitHub API results are marked `source=github_live`. No stale
  health-snapshot fallback is performed.
- Run details include up to 100 jobs. Runs with additional jobs return an
  explicit `github_jobs_truncated` error instead of pretending completeness.
- Queries and responses have bounded limits, a 10-second network timeout and
  a 256 KiB response cap; API failures use stable error codes.
- Workflow errors currently include the failed **job and step metadata**
  only. Raw CI logs can contain secrets and are intentionally withheld;
  `logs_available=false` and `log_excerpt=withheld_untrusted_build_output`
  make this explicit. Do not interpret this as full log diagnostics.
- There are no workflow rerun, cancel, dispatch, approve or mutation tools,
  and no automatic Codex execution.

## Agent acceptance checklist

1. Run PR CI, including `tests/mobile/test_mcp_workflows.py`, the existing
   `test_mcp_agent.py` and `test_mcp_http.py`, and the gateway smoke tests.
2. Check malformed input, unauthorized repository rejection, statuses,
   missing credentials, API error codes, incomplete pagination and response
   truncation. Never use live GitHub credentials in CI.
3. After merge and a separately approved MCP activation, run a live
   **read-only** query on a known run and cross-check the returned URL,
   run ID, status, jobs and failed steps against GitHub.
4. Record PASS/FAIL/BLOCKED and sanitized evidence on issue #243.
   Never claim ChatGPT connectivity before the actual plugin connection works.

## Future optional extension

If detailed error excerpts are necessary, introduce a separately reviewed
credential-aware log redaction and explicit opt-in mechanism. Arbitrary
raw logs are not safe to expose to an LLM by default.
