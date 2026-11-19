# Development Evidence V3 — minimal operational acceptance

V3 is a **pure read-only** acceptance projection of already available
terminal deployment records and local node status. It does not perform
network calls, SSH, GitHub calls, authentication, writes or deployments.
The existing operator may supply observations through already authorized
readers. This is not a new MCP tool or another permission gate.

## Sources and scope

1. Existing backend GitHub Actions **push** workflow receipt for an exact
   40-character main SHA. Require a completed/successful workflow and
   exactly three successful terminal jobs: hosted admission, `deploy` on
   gway-001, and `Deploy Watchtower MCP`.
2. Existing read-only release symlinks on gway-001 and Watchtower, both
   independently observed at that SHA. Require a distinct previous
   revision as available rollback evidence; do not test rollback.
3. Existing `gway-remote status --json` deep envelope on gway-001.
   It establishes that the existing health reporter responded, not that
   all appliance targets have passed functional acceptance.
4. Existing Watchtower service observations for the MCP gateway, link and
   enrollment owner. These must all be active.

The collector is deliberately **not** connected to a new runtime entrypoint.
The preexisting GitHub and node read authorities obtain the observations.
V3 only projects the data they return; source claims are not additional
authentication or attestation.

The output is `gway.operational-acceptance.v3`. `accepted` means the
exact deployment workflow finished and both existing node observations
are timely and internally consistent. Missing/contradictory evidence,
incomplete jobs, failed health, bad revision or stale/future observations
return `unknown` or reject malformed input. A positive outcome is **not**
a deployment authorization and does not imply a full application-level
functional test. Each observation uses the same bounded 300s default TTL,
adjustable 1..604800s.

The existing deploy impact allowlist excludes this new V3 file.
**Do not merge** without separate operator authorization for the existing
gway-001 and Watchtower auto-deploy. #565, #614 and #617 remain independent.
