# GitHub Health Watch — mobile integration contract

Tracking: #144

## Source of truth

The hourly diagnostic-only watch is an independent producer. Android must **not** run a second poller, inspect GitHub directly, or dispatch a workflow. Until the producer has a durable output and an authenticated backend endpoint, the UI must display **Unavailable**, never **Healthy**.

## Allowlist

Exactly these repositories:

- `arthexis/ocpp-csms`
- `arthexis/gway-remote`
- `arthexis/ocpp-simulator`
- `arthexis/gway-rfid`
- `arthexis/gway-ap-kiosk`

Reject unexpected repositories from any ingested report. Deprecated repositories are not queried.

## Proposed read-only API

`GET /api/github-health` (existing mobile API authentication required).

Response schema version 1:

```json
{
  "schema_version": 1,
  "status": "available",
  "completed_at": "2026-10-18T20:00:00Z",
  "repositories": [
    {"name": "arthexis/ocpp-csms", "pass_a_checked": true, "pass_b_checked": true}
  ],
  "alerts": [
    {
      "id": "arthexis/ocpp-csms:main:ansible:base-sha:episode-1",
      "repository": "arthexis/ocpp-csms",
      "state": "ACTIVE",
      "category": "CI_FAILURE_STUCK",
      "title": "Main Ansible integration",
      "first_observed_at": "2026-10-18T07:38:00Z",
      "evidence_url": "https://github.com/arthexis/ocpp-csms/actions",
      "next_action": "Check the main push base SHA"
    }
  ]
}
```

The example is illustrative, not live health data. Production responses must cover all five repositories with both pass flags true before reporting a complete snapshot. Missing, stale, invalid, or unauthenticated source data is an explicit unavailable/error state.

## Lifecycle and UI

- Alert IDs include repository, lane/PR, root cause and episode; they remain stable until retirement.
- RESOLVED records carry `resolved_at` and `resolution_kind` (`fixed`, `cancelled`, `superseded`, `closed_without_fix`, `reclassified`).
- Android displays last completed check, stale/unavailable state, ACTIVE and RESOLVED tabs, repo filter, evidence deep links and refresh of cached data.
- A refresh is GET-only; never rerun, merge, deploy, repair, or mutate GitHub.
- Historical resolutions are not re-notified; no-change snapshots generate no alerts.

## Delivery gates

1. Identify and persist the existing watch's actual report format and alert lifecycle store.
2. Implement authenticated, bounded backend GET response with allowlist and schema tests.
3. Implement Android panel in the existing panel registry; verify empty, stale, invalid and error states.
4. Validate backend/APK compatibility and CI before enabling the screen.

This document intentionally does not claim a running producer, backend endpoint, or Android feature.
