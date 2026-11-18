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
  `unknown`. The projection deliberately excludes private logs/errors.
- `development_snapshot(receipt=..., github_head=..., ci=...)` takes an
  independently observed GitHub HEAD and CI conclusion. It classifies
  `unknown`, `blocked`, `pending` and `accepted` without querying any
  external service. A `verified` projection means *the supplied* observations
  match; it is not itself an attestation or authorization.
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
