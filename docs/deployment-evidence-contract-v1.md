# Deployment evidence contract v1

Status is **observed evidence**, not an interpretation of deploy exit codes, CI, Git HEAD, or a role marker. This document defines the read-only interoperability target for GWAY-managed repositories (issue #225). Existing repository-specific probes and APIs remain supported until adapters are implemented.

## Canonical JSON envelope

```json
{
  "schema_version": 1,
  "repository": "example/component",
  "source_revision": null,
  "staged_revision": null,
  "activated_revision": null,
  "installation_state": "unknown",
  "runtime_state": "unknown",
  "observed_at": null,
  "evidence": [],
  "errors": [],
  "capabilities": {
    "staging": false,
    "activation": true,
    "runtime_probe": true,
    "runtime_required": true
  }
}
```

All revision fields are nullable strings containing verified immutable revision identifiers. `source_revision` is the requested build/source revision, **not** proof of installation. `staged_revision` and `activated_revision` must be independently evidenced; they may differ. `observed_at` is an RFC 3339 UTC timestamp of the actual probe, or null if no trustworthy observation exists. `evidence` is a list of sanitized, stable descriptions or identifiers of observations (never credentials); `errors` contains sanitized probe errors.

### State semantics

- `installation_state`: `unavailable` (authoritatively absent), `staged` (verified staging, not activation), `activated` (verified selected active release), `unknown` (missing, invalid, inaccessible or conflicting evidence).
- `runtime_state`: `healthy` (independent successful runtime probe), `unhealthy` (independent negative runtime probe), `unknown` (not probed, stale, inaccessible or inconclusive), `not_applicable` (no runtime service is expected by design). A successful installer is **not** a runtime probe.
- `capabilities.staging`: supports a staged release distinct from activation. `activation`: activation exists as a meaningful operation. `runtime_probe`: an independent runtime probe is available. `runtime_required`: a running service/process is required for normal operation. CLI-only or intentionally staged-only packages may use `runtime_required=false` and `runtime_state=not_applicable`.
- An activated revision does not imply healthy runtime. A healthy probe does not by itself identify the active revision. A role marker proves neither.
- Missing, malformed, symlink-escaped, contradictory or partially read evidence must fail closed: report `unknown` for the affected claim and preserve a sanitized error; never silently promote staged to activated.
- Evidence freshness is determined from `observed_at` and a consumer-defined maximum age. Stale observations cannot support a current `healthy` claim; retain their historical values only if explicitly labeled stale by the consumer.

## Producer requirements

Each repository should expose a local, non-mutating, unprivileged JSON status command. It must not call deploy, activate, sudo, network-changing operations, secret readers, or hardware actions. Installer/activator owns atomic evidence writes and explicit filesystem permissions. Probe reads verify the active release target and runtime independently, without assuming systemd applies to every component.

The adapter may map existing evidence into this envelope; repositories do not have to adopt identical installation layouts. Do not require a schema migration or production redeployment just to read status.

## Consumer requirements

GWAY Remote must keep installation and runtime status separate in CLI, API, and Android UI. It must not infer installed revision from requested SHA or classify `not_applicable` as unhealthy. Unknown, stale or failed probes remain visible rather than being converted to success. Keep compatibility with existing API fields during incremental rollout; do not change their meaning silently.

## Acceptance matrix (PR-only tests)

| Fixture | Installation | Runtime |
| --- | --- | --- |
| No evidence, inaccessible evidence | unknown | unknown unless independently probed |
| Valid staged-only record | staged | not_applicable when no runtime required |
| Verified activation, no runtime proof | activated | unknown |
| Verified activation, passing probe | activated | healthy |
| Verified activation, failing probe | activated | unhealthy |
| Malformed/contradictory revision evidence | unknown | independently determined |
| CLI-only installation, no service expected | activated when verified | not_applicable |
| Stale runtime observation | preserve verified installation | unknown for current health |
| Repeat identical probe | no state mutation | idempotent |

## Rollout

M1 Bastion staged/activated adapter: see PR #226 and #240; validate against this contract without changing protected activation. M2: this contract and adapter guidance. M3: inventory actual probes for every managed repo, including dynamically discovered deploy-all targets. M4: incremental repository adapters and aggregated fixture-based Remote contract tests. No forced redeploy, database reset, production SSH/USB/hardware actions, or protected Bastion activation.
