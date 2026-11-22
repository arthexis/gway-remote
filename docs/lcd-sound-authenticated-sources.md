# Issue #687 — authenticated server-origin LCD/Sound delivery

## Current implementation status

This change introduces the **pure source-grant authorization seam**,
a **Watchtower-side programmatic forwarding adapter** and regression tests. It does not expose a network endpoint or enable external
origin messages in the installed node receiver. The existing Watchtower-only
receiver remains the default.

The following conditions are **required before enabling an ingress**:

1. Identify the actual service/OS users and event producers on
   `ocpp-abb-1` and `gelectriic.com`. Do not assume the interactive
   `ubuntu` installation is the production event producer.
2. Establish the existing trusted authentication service on Watchtower.
   Extract a non-client-controlled principal from its verified auth context,
   scoped to a single external source. Neither DNS, claimed `origin`,
   unverified headers, nor an SSH command argument establishes that identity.
3. Load grants from an operator-owned, validated policy file with separate
   identities for `ocpp-abb-1` and `gelectriic.com`, explicit permitted
   `gway-001` target and minimal LCD/Sound operations. Provide revocation.
4. Call `lcd_sound_source_policy.authorize(event,
   verified_principal=authenticated_context.subject, grants=operator_grants)`
   before dispatch. **Do not pass client-controlled strings as
   `verified_principal` or allow an unprivileged account to edit grants.**
5. Relay authorized events over Watchtower's existing pinned SSH transport.
   The node must bind the origin to an authenticated Watchtower assertion or
   separately verified source context, not merely the untrusted event body.
   Do not copy Watchtower SSH credentials to either server.
6. Keep the receiver's private at-most-once journal, no-local-fallback
   behavior, expiry and request-ID binding. Do not retry uncertain hardware
   events with new request IDs.
7. Test per-source ingress, missing/revoked grants, malformed requests,
   wrong destination, physical status/show/play, and rollback in an isolated
   authorized canary before turning on any production route.

## Proposed event producer coverage

Audit before selecting actual producers. Candidate integration is an explicit
`gway-lcd-sound` wrapper for allowlisted application notifications and
operator-submitted diagnostic events. Keep ordinary system LCD monitoring and
local hardware diagnostics local unless explicitly approved. Merely installing
the `gway-sound-route` shim does not migrate existing users of `sound`.

## Rollout/rollback contract

No change to OCPP, GWay MCP or Odoo service accounts, SSH ForceCommand, peer
configuration, or ports is part of this stage. Deactivation first revokes a
source grant at the authenticated ingress; then resets only that sender's
per-user LCD/Sound route to local. A verified route must fail closed (no local
fallback) on revocation or delivery failure. Check and record prior release
symlinks and exact revisions before any installation. Preserve both servers'
business services, and do not claim physical display/audio evidence from an
acknowledgment alone.

## Outstanding integration

An externally reachable authenticated ingress, verified-principal extraction,
service-account inventory, producer migration, and hardware validation are
**not implemented** by the Draft PR. The programmatic ingress adapter calls
`forward_authenticated(event, authenticated_principal=trusted_context.subject,
operator_grants=operator_owned_grants)` only after an existing service has
verified the caller. It checks the origin against the grant and then stamps the
pinned node relay envelope as Watchtower, since the node can verify Watchtower's
SSH key but cannot verify a server principal. The original source and the SHA256
of its event appear in the Watchtower ingress receipt. The forwarded receiver
request ID is deterministic for (verified principal, source, client request ID),
so separate servers cannot collide in the receiver journal with the same
client-chosen ID; the source-visible receipt retains the original request ID. This is a hop-by-hop
trust design: source identity is asserted by the trusted Watchtower ingress,
not independently authenticated by the node. No new external endpoint exists.
The adapter MUST NOT be exposed to an untrusted caller without authenticating
and authorizing the caller and loading current operator-controlled grants.
Further integration must define audit persistence and ensure the producer's
stable request IDs survive network retries. They are explicit
completion gates for issue #687.

## Protected grants

The staging code includes a fixed-path read-only loader for
`/etc/gway-remote/lcd-sound-sources.json` with schema 1, bounded size,
`O_NOFOLLOW`, and root ownership. It is intentionally **not** installed
or read by any production service yet. An illustrative, non-secret
operator-owned configuration is:

```json
{
  "schema": 1,
  "grants": {
    "authenticated-subject-for-abb": {
      "source": "ocpp-abb-1",
      "targets": ["gway-001"],
      "operations": ["lcd.show", "lcd.status", "sound.play", "sound.status"],
      "enabled": true
    },
    "authenticated-subject-for-gelectriic": {
      "source": "gelectriic.com",
      "targets": ["gway-001"],
      "operations": ["lcd.show", "lcd.status", "sound.play", "sound.status"],
      "enabled": true
    }
  }
}
```

These subject strings are placeholders, **not** real accounts or credentials.
Resolve and verify the actual service identities first. Revocation changes
`enabled` to false in the root-owned snapshot and atomically republishes it;
the ingress must reload the latest trusted snapshot for each request or use
an equivalently bounded freshness/revocation mechanism.

## Observed runtime limitation from #687

The issue reports that `gway-lcd-sound` revision
`41cc1bbd3894a10fb29f44ab9019e7b9e7f1b7ba` was verified for the
interactive `ubuntu` account on both servers, but route probes failed.
This does **not** establish which production users emit events. Real unit
files, process credentials, calls to legacy `sound`/`lcd`, and actual
`PATH` must be inventoried on each host before remapping any producer.
Keep an explicit distinction between transport-receipt success and
human-observed physical LCD/audio output.
