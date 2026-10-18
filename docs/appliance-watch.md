# Appliance watch

GWay Remote owns appliance-wide deployment orchestration and incident routing.

## Operator commands

- `gway-remote watch` — read-only single reconciliation tick.
- `gway-remote watch --apply` — dispatch **at most one** eligible deployment through the existing GitHub Actions appliance workflow and upsert runtime incidents.
- `gway-remote deployments` — compare observed installed releases with current main.
- `gway-remote diagnose [component]` — inspect sanitized local evidence.
- `systemctl status gway-remote-watch.timer`
- `journalctl -u gway-remote-watch.service -n 100 --no-pager`

The GWay Remote Ansible installer enables `gway-remote-watch.timer` (15-minute
interval). The timer invokes the installed `/usr/local/bin/gway-remote` zipapp,
running as the appliance user `arthe`, not root.

## Dispatch and safety

The appliance user must have an authorized `gh` login with repository
dispatch access, **and** write access for incident issues. The existing
`appliance-deploy.yml` workflow authorizes only dispatches by `arthexis`.
Authentication/permission errors fail the watch tick visibly in systemd.

The watch does **not** install software directly. A target is eligible only
when its active installed revision is independently observed, is behind main,
the new exact SHA has not been attempted, main-push CI for that SHA is
successful, and the main commit is at least ten minutes old.

An installed SHA marked `unknown` is **not** a reason to deploy. These
components are deliberately skipped until the installer supplies independent
revision evidence. A failed revision is not retried automatically; an
operator can issue `gway-remote deploy <repo>` for an explicit retry.
The watch does not create repeated no-op Actions runs; it asks GitHub for
queued or running appliance runs before dispatching one eligible repo per tick.

## Incident ownership

- Deployment dispatch and workflow/installer failures belong to
  `arthexis/gway-remote`. The existing Appliance Deploy workflow already
  maintains reusable deployment failure issues per target.
- Runtime health failures are upserted under their **component's repository**
  using a stable `gway-remote:appliance-watch` marker.
- Updating an incident with unchanged details is a no-op. No incident is
  automatically closed when health recovers; operators review resolution.
- The watch issue body includes only a short categorization and reason, not
  raw logs, environment variables or credentials.

The GWay Remote backend's automatic self-deploy is separate from the
appliance deployment workflow; enabling this timer does not implicitly run
`deploy --all`.

## Revision provenance

- CSMS, LCD Sound, RFID and Simulator: existing immutable-release symlinks.
- Reports and Agent Ops: installed executable symlinks into a SHA-named
  release directory; reject broken and malformed release links.
- AP Kiosk: `/var/lib/gway-ap-kiosk/installed-revision`, written **after**
  successful HTTP/service health validation by the kiosk installer. Until
  that installer version is deployed, kiosk stays unverified.

Any remaining `unknown` evidence causes a safe skip, not a guessed SHA.
