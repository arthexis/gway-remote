# Issue #687 — authenticated server-origin LCD/Sound delivery

## Current implementation status

This change introduces only the **pure source-grant authorization seam** and
regression tests. It does not expose a network endpoint or enable external
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

The network ingress, authenticated principal extraction, receiver proof of
origin, service-account inventory, producer migration, and hardware validation
are **not implemented** by the source-policy-only Draft PR. They are explicit
completion gates for issue #687.
