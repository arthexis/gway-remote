# GitHub MCP read-only inspection — R1

R1 adds two built-in tools without changing deployment or workflow dispatch:
`github_branch_effective_rules(repository, branch)` and
`github_commit_checks(repository, sha)`.

Both have MCP `readOnlyHint=true`, require the gateway's authenticated
`gway:read` path, and use the existing bounded repository allowlist derived
from `export_targets()`. The GitHub credential is the existing protected
`GWAY_MCP_GITHUB_TOKEN` (distinct from the gateway OAuth bearer). Grant only
GitHub Metadata:read, Checks:read, and Commit statuses:read for allowed repos;
do not expand the token's write privileges. R1 does not rotate or install tokens.

The API client performs GET requests only against fixed relative routes:
`/repos/{repo}/rules/branches/{branch}`,
`/repos/{repo}/commits/{sha}/check-runs`, and
`/repos/{repo}/commits/{sha}/statuses`.
No caller-selected URLs or arbitrary API paths are accepted. Branches and
lowercase full SHA-1 commit IDs are validated before any network I/O.

The response includes a schema version, exact repository/branch or SHA,
`source=github_live`, `complete=true` only after successful bounded reads,
effective rule source metadata and check-run GitHub App ID. The tools collect
evidence but NEVER declare a merge eligible; unknown rules and checks require
separate evaluation. Explicit errors preserve inaccessible, invalid, rate-
limited, truncated and inconsistent cases. There is no stale fallback.

At most 10 pages of 100 rules, checks or classic statuses, 256 KiB per response,
10-second per-request timeout; incomplete data is an error. A short page
proves array-endpoint termination; a full tenth page fails closed. Rules
are not proof that the branch exists. Check runs request filter=all, and an
additional GitHub check-suite count fails closed at >=1000 suites because
GitHub's per-ref check-run endpoint is limited to the latest 1000 suites.
Counts remain subject to upstream concurrent changes; this is not an atomic
GitHub snapshot. Redirects are rejected and no raw logs or secrets returned.

Hermetic tests: `python -m unittest tests.mobile.test_mcp_github_read -v`.
After merge, a separate authorized operational release is necessary before
these tools can be asserted available through live Watchtower federation.
