# Development evidence V1 (offline projection)

This incremental module is **not** a broker, watcher, scheduler, deploy
endpoint, or separate ledger. It only projects caller-supplied observations.

## Sources and trust

- Appliance Deploy owns the existing `attempts.json` journal. Its statuses
  (`started`, `failed`, `staged`, `installed`) describe installer attempts;
  they do not prove the release currently active on a host.
- `deployment_receipt(name, attempt, observed_sha=..., health=...)` accepts
  an existing journal entry and independently supplied **read-only** installed
  revision and health evidence. Until independently observed, both are
  `unknown`. Matching SHA plus supplied healthy status yields `evidence=consistent`,\n  never `acceptance=verified`: provenance, freshness and functional acceptance\n  are not represented in V1. The projection excludes private logs/errors.
- `development_snapshot(receipt=..., github_head=..., ci=...)` takes an
  independently observed GitHub HEAD and CI conclusion. It classifies
  `unknown`, `blocked`, `pending` and `review` without querying any
  external service. `review` indicates only self-consistent supplied evidence,\n  not a verified installation or an accepted release. Forged or noncanonical\n  receipt dictionaries are rejected.
- No network, host files, subprocess, MCP, SSH or GitHub operations occur
  inside these functions. Neither function causes or permits a deployment.
- Invalid SHA, timestamp, status, CI or unknown target fail closed. A missing
  observation is never replaced with the current GitHub HEAD.

## Relationship with existing work

- **#565 Appliance Deploy**: reuse its reviewed catalog and attempt journal;
  do not synthesize permissions from a catalog entry or bypass owner installers.
- **#614 independent nodes**: Watchtower node-exec terminal receipts and
  attestation are a different evidence family, not interchangeable with
  Appliance Deploy installation receipts. No change to gway-002/004.
- **#617 executor identities**: a future federated adapter must preserve
  observed node and executor identities, never accept caller-selected OS
  users. V1 does not read or alter an executor identity.

## Phases

1. **V1 (this PR)**: pure read-only normalization and a fail-closed snapshot
   with hermetic unit tests. Not connected to a runtime entrypoint.
2. **V2 (separate review)**: authenticated read-only adapters for the existing
   attempt journal, installed-release probes and CI, with source/time/provenance,
   bounded queries and explicit unavailable/error handling. Preserve privacy.
3. **V3 (separate review)**: acceptance diagnostics including Watchtower
   terminal receipts and authorized scope-specific health checks, without
   implying deployment permission or merging evidence families.
4. **V4 (optional, only after acceptance)**: resumable lifecycle coordination
   referencing existing ledgers and operator policies; no new daemon.

No new issue is necessary until the existing overlapping issues have been
reviewed and this small baseline has CI evidence. No production cutover,
merge, release or installation is authorized by this document.

## Auto-deploy push impact admission (PR #632, still not activated)

The existing `.github/workflows/deploy-backend.yml` deploys gway-001 and
Watchtower on every `main` push. This PR proposes a hosted read-only
`admission` job before either self-hosted deployment job. It compares the
complete Git `github.event.before..github.sha` range and emits a strictly
binary deployment decision. Only these **exact** V1 non-runtime paths are
allowlisted:

- `docs/development-evidence-v1.md`
- `tests/deployment/test_development_evidence.py`
- `gway_remote/development_evidence.py`

Any other changed path (including this workflow, the impact classifier,
deployment scripts, configuration or future code) requests the **unchanged**
existing deployment jobs. Missing history, force pushes, invalid/empty diffs
and an admission failure block both jobs, rather than silently declaring
an offline-only update. A blocked operational push requires explicit
investigation and manual remediation; it does not become "up to date".
No new permissions, credentials, targets or services are introduced.

**First-merge bootstrap limitation:** The guard changes the workflow file
itself. Accordingly, its first merge is classified as operational and would
trigger existing gway-001 and Watchtower auto-deploy. Do **not** merge this
PR under a no-deploy constraint. A separately approved deployment window or
a verified external pre-merge control is required for first activation; the
PR's green tests cannot prove production deployment suppression. Once
activated, a later merge containing only the three allowlisted paths may
skip deploy, but each push must be evaluated independently.

The narrowly allowlisted Python module has no import path from production
entrypoints in this increment; expanding its callers or changing unrelated
runtime files is operational. The allowlist must be reviewed again when V2
integrates runtime adapters.
