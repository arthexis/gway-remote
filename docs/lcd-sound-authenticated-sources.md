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

## Existing Watchtower bearer verification integration

The opt-in `forward_verified_bearer` adapter now uses the existing
`BearerVerifier.lcd_sound_principal(token)`. This validates the
`gway:lcd-sound` scope, expiry and delegation-chain revocation on **every**
request and derives the stable parent key ID as the source principal; a
client-supplied `origin`, hostname, token prefix or header does not establish
that principal. An independently root-owned grant maps each verified ID to
exactly one allowed server source. The gateway is not yet wired to an external
route, so no server can use this adapter over the network today.

When provisioning, issue two **different operator-approved credentials** via
the existing audited bearer issuance mechanism, one held by each existing
server service account; configure two separate root-owned grant entries using
the verifier's stable IDs, never copying Watchtower's SSH identity. A
`gway:lcd-sound` bearer cannot access general MCP read/execute tools, and
ordinary read/execute/combined bearers cannot authorize this dedicated source
scope. A separate source grant is required in addition to the bearer. Do not put tokens or private keys
in the configuration file, Git history, or logs. Revoke either credential and
its source grant separately; the next request must fail before the pinned
transport is invoked. This describes a future controlled provisioning step;
no real credentials were created for the two servers in this PR.

The previously documented example `authenticated-subject-for-abb` and
`authenticated-subject-for-gelectriic` are illustrative; actual verified
principals are the 24-character hexadecimal values issued by Watchtower's
existing bearer registry.

## Default-off HTTP admission on the existing gateway

A **loopback-only** `POST /v1/lcd-sound/event` path is now implemented
inside the existing bearer gateway handler. Its default is disabled:
`make_server(..., lcd_sound_ingress_enabled=False)`, and the deployed
gateway's `main()` does not change this default. Unknown paths still
return 404. No Nginx mapping or external listener is provided.

Only trusted, explicitly enabled gateway construction can expose this
path on its loopback socket. It requires exactly one valid
`Authorization: Bearer ...` value, JSON content type, bounded length,
no untrusted Origin header, a current `gway:lcd-sound` credential
verified through the existing registry, and a separate currently
enabled root-owned source grant. It returns HTTP 200 for acknowledged
success, 202 for uncertain and 502 for reported failure; it never
replays an ambiguous hardware event with a new request ID.

Before production use, a separately reviewed HTTPS/Nginx mapping and
per-host token provisioning are required, with **no** broadening of
the standard MCP `/mcp` endpoint or leakage of the gateway's pinned
SSH credentials. Verify the existing SSL/frontend topology, HTTP request
limits, the gateway's service user and root-only policy path; physical
acceptance on gway-001 remains a separate gate. Do not enable based solely
on green hermetic tests.

## Reviewed-only activation and safe host inspection

The gateway's `main()` **still defaults to disabled**. For a separate
controlled Watchtower rollout only, the operator may set
`GWAY_LCD_SOUND_INGRESS_ENABLED=1` on the existing bearer gateway service
**after** confirming that its pinned execute relay is enabled and a
root-owned `/etc/gway-remote/lcd-sound-sources.json` exists and passes the
private grant loader. Missing pinned execution or unsafe grants prevent
startup, rather than opening an unauthorized ingress.

The new standalone `deploy/nginx/gway-lcd-sound-ingress.conf` is **not**
included by any default Nginx site; after inspecting the live TLS vhost,
an operator may stage it under the existing `remote.arthexis.com` TLS
server block, run `nginx -t`, reload reversibly, and prove POST-only
behavior. It proxies to the existing loopback bearer gateway port 19010,
with bounded request size and no new public port. Existing `/mcp` remains
unchanged. This PR does not configure Nginx or Watchtower services.

`scripts/lcd-sound-acceptance-audit.py` is a **read-only, non-root**
local helper to run independently as each real prospective producer
account. It prints only selected process/service metadata and file
ownership/modes; it never prints tokens, environment values or private
SSH keys, runs no hardware command and makes no service change. Its
output is evidence to compare against the reported interactive `ubuntu`
installations, **not evidence that any host was inspected in this PR**.
Run it under each host's actual account only after authorized access.

Required acceptance evidence per host: `hostname`, effective user,
source-config/token file metadata (no content), installed LCD/Sound
release SHA, GWay Remote gateway/service version, systemd User/MainPID
and actual event-producer callsite, a fresh status receipt from
`gway-001`, a benign display/sound event receipt, and an independent
human observation (if required). Revoke the exact source grant and
credential and prove subsequent attempts fail closed; restore previously
captured route/release state if needed. The two server checks must be
recorded independently, with no customer OCPP/Odoo/MCP interruption.

### Credential issuance and revocation (separately authorized rollout)

The existing Watchtower-only `scripts/mcp-bearer.py` now accepts
`issue --scope gway:lcd-sound --days 1` under the dedicated registry
owner. Each invocation creates **one** source-only credential and returns
it once. The operator must keep the plaintext out of Git, chat, process
arguments and logs. The 24-character key ID returned by the trusted
`BearerVerifier.lcd_sound_principal` becomes the source-grant map key.
Issue separate credentials under the two server service accounts only
after confirming their actual identities. The existing CLI command
`revoke KEY_ID` invalidates the credential independently of grant
`enabled=false`. In tests, both revocation paths are checked.
This documents the supported console operation; **no production
credentials were issued during this development run**.
