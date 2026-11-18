# Development Evidence V2 — offline source adapters

This increment is deliberately a **pure projection**. It does not fetch data,
connect to nodes, issue MCP commands, authorize an installer, store receipts or
change the existing V1 public contract.

## Existing source contracts

- **Attempt journal**: `attempts.read_attempts()` supplies the recorded
  attempt (`sha`, `status`, `at`) and a separate caller-recorded collection
  timestamp. The attempt timestamp is **not** the observation timestamp.
- **Installed release**: `status.status(depth="deep")` and its existing
  `deployment_evidence` row supply the local gway-001 observation, runtime
  and activation states. The adapter rejects different/unknown nodes,
  quick-depth probes, duplicate/missing targets and inconsistent repository
  and timestamp metadata. It never reads another node's local filesystem.
- **GitHub HEAD and PR CI**: the existing `github_state` read client is
  responsible for fetching branch and CI data. V2 accepts only a caller-
  supplied full SHA, exact `ci_head_sha`, CI status and independent read times.
  It does not make API requests.

The `development_evidence_v2(...)` adapter accepts these envelopes, an aware
`now` timestamp and a **complete** freshness policy in seconds for journal,
release, github and ci. Defaults: 86400, 300, 300, 300. Freshness measures
when the source was read, not the age of the original attempt or commit.
Future and expired observations are untrusted. TTL values must be integer
seconds in 1..604800.

## Result and limitations

Schema `gway.development-evidence.v2` contains declared source, node,
repository, observation time, freshness, fixed reason codes and a sanitized
V1 receipt. A stage of `review` only means internally consistent supplied
evidence; **it never proves authenticated provenance**. Functional
acceptance and source attestation remain `unknown` and `unverified`.

Abbreviated 12-character installed SHAs are not proof of equality with full
GitHub SHAs. Staged-only Bastion, missing releases, unknown health, CI
failure, stale sources and missing journal entries cannot produce `review`.
Errors and private journal log paths are never copied to the projection.

Source and node metadata are claims from caller-supplied responses, not
cryptographic attestations. No runtime entrypoint is added. V3 requires
separate authenticated collection and functional acceptance.

The deploy workflow and impact gate remain unchanged. Since this PR adds
files outside the reviewed V1 allowlist, any merge remains operational
and requires separate authorization. #565, #614 and #617 stay independent.

## Audit hardening (PR #633)

A clean `review` now additionally requires a journal status of `installed`,
not merely a coincident requested SHA; staged/failed/started attempts remain
unknown. The entire existing `deployment_evidence.validate` envelope is
checked, including required fields, evidence list and capability flags.
Recorded probe errors, absent active-release evidence, and activation times
after the observation all block review. The journal entry timestamp cannot
postdate the journal collection timestamp. These are consistency checks on
caller-supplied snapshots; they still do not authenticate the source or prove
a running production release has passed functional acceptance.
