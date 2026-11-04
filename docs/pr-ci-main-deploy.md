# PR validation and automatic gway-001 deployment

The intended lifecycle is:

1. A pull request runs **Python checks**: all five unittest/pytest subsystem
   groups, architecture, CLI/shell, Ansible syntax, Debian SSH validations.
2. The stable **CI** job aggregates the results. It fails if **any** required
   test job fails, is cancelled, or is skipped.
3. Merge is allowed only if the repository's **main ruleset requires the
   `CI` status check**. This is a GitHub repository setting; a workflow file
   alone cannot enforce it.
4. A push to `main` immediately schedules **Deploy GWay Remote backend**
   on the gway-001 self-hosted runner. It verifies that its SHA is still
   current, checks installation prerequisites, invokes the existing
   transactional/idempotent `deploy.sh`, and verifies runtime status.
   It does **not** rerun the unit suite.
5. A new push supersedes an older queued revision; the older run is skipped.
   Existing deployment serialization remains unchanged.

## Required GitHub ruleset configuration (operator action)

The active `main` ruleset at
https://github.com/arthexis/gway-remote/rules/24802372 currently requires a
pull request but has **no required status checks**. Add the required status
check **`CI`**, sourced from GitHub Actions, to this ruleset. Existing PR
requirements and deletion/non-fast-forward protections must remain.

Do not require the deployment workflow as a pre-merge check: deployment runs
only after merge. PR CI must complete at least once so GitHub can discover
the `CI` status-check name before it can be selected.

## Operational distinction

- A failing PR check blocks merging once ruleset enforcement is configured.
- A failing main deployment indicates **deployment prerequisites, install,
  service restart, or runtime health**, rather than duplicate test-suite
  failures. Live deployment failures can still occur after a passing PR.
- A deliberately skipped older main revision is not a failed deployment.
- Merge commits should not be used to bypass the PR gate; keep the active
  ruleset and required check in place.
