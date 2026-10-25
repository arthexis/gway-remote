# Watchtower production enrollment owner

This runbook is for R3 of the Watchtower enrollment rollout.  The production
owner is deliberately separate from the R2 `--read-only-stage` service.

## Install without activation

Use `ansible/playbooks/watchtower-enrollment-production.yml` only against the
Watchtower, with `watchtower_enrollment_production_apply=true` and values
observed during the R1 preflight for the WireGuard network, gateway, and UDP
endpoint.  The role refuses empty values and unsafe WireGuard configuration
metadata.  A newly installed unit is not started or enabled by this role; a
default re-run also leaves its current runtime state untouched.  It does not
enable an enrollment route, touch peers, issue invitations, or change gway-001.

The role installs the request-safe `gway_enrollment_safe` Nginx log format
under `/etc/nginx/conf.d` and validates it with `nginx -t`; it does not reload
Nginx.  It also stages the exact `/v1/enroll` fragment beside the Watchtower
application for review.  The format excludes request URI, query, body, and
headers.

The service is root-owned only because enrollment provisioning must atomically
update the protected WireGuard configuration and perform a narrow `wg set`.
It is loopback-only, has a root-owned ledger and backup directory, and confines
writes to the WireGuard directory plus those two directories.

## Reviewed R3 activation sequence

1. Record current peer count, the preserved gway-001 peer's handshake/counter,
   active Nginx upstream, legacy health response, and the protected backup
   locations. Confirm that no invitation is pending.
2. Stop and disable only the R2 stage. Keep the legacy service running for
   immediate upstream rollback. Enable and start the production owner on its
   already-reviewed loopback port, then check its local health and malformed
   enrollment response. Do not issue an invitation.
3. Add the staged `gway_enrollment_safe` access log only to the exact
   `/v1/enroll` location, then change only the two public enrollment/health
   upstream references. Validate with `nginx -t`, then reload Nginx. Verify
   public health identifies gway-remote, malformed enrollment remains rejected,
   and the public enrollment route has the safe log override. Do not restart
   `wg-quick@gway`, rotate keys, or modify existing peers.
4. Confirm the gway-001 peer remains in both runtime and persistent
   configuration and that its natural handshake/counters continue. Leave the
   legacy service installed until R4 field enrollment succeeds.

If the production owner or routing health fails, restore only the captured
service/upstream state, retain the ledger and WireGuard backups, and report the
ambiguous state. Never remove peers or attempt broad automatic rollback.
