# gway-remote

Central job dispatcher and managed runner workloads for `gway-001`.

## Design

Personal-account repositories trigger **repository_dispatch** on this repository. Only this repository schedules the self-hosted runner. The source repository never needs direct access to that runner. There is no organization requirement.

The initial job catalog is deliberately narrow:

- `system-health`: read-only environment diagnostics
- `ocpp-simulator`: isolated OCPP simulator smoke test at a pinned commit from `arthexis/ocpp-csms`
- `lcd-sound-deploy`: deploy only the verified LCD Sound `main` SHA to Gway-001 after passing its tests; keep observer shadow-only
- `ocpp-stage`: reserved for a future audited deploy path; **not yet enabled**

No event payload can specify a command, workflow, checkout URL, or host path.

## Setup

1. Register the existing `gway-001` ARM64 runner with **this repository**, using labels `self-hosted`, `Linux`, `ARM64`, `gway-001`. Stop/unregister it from `ocpp-csms` **only after migration works**.
2. Grant each trusted caller a fine-grained GitHub token (or preferably a GitHub App installation token), with **Contents: read/write** access to `arthexis/gway-remote` sufficient to create repository dispatch events. Store it as `GWAY_REMOTE_DISPATCH_TOKEN` in the *calling* repository's Actions secrets. Never put this token in untrusted PR jobs.
3. Configure the calling workflow to dispatch one of the approved events. Do not grant dispatch permission to fork PRs or unreviewed workflow modifications.
4. Ensure `gway-001` has Python 3, `git`, and access to the public source checkout. The initial simulator job uses a private temporary checkout and virtualenv.
5. Run `workflow_dispatch` with `system-health` first, and confirm the runner labels match.

### Example caller workflow step

```yaml
- name: Dispatch simulator to gway-001
  env:
    GH_TOKEN: ${{ secrets.GWAY_REMOTE_DISPATCH_TOKEN }}
    SHA: ${{ github.event.pull_request.head.sha }}
  run: |
    gh api repos/arthexis/gway-remote/dispatches \
      -f event_type=ocpp-simulator \
      -f client_payload[repository]=arthexis/ocpp-csms \
      -f client_payload[sha]="$SHA"
```

**Security:** only enable this for trusted same-repository PR heads authored/approved by the maintainer. The dispatch API authenticates the *token*, not the provenance of `client_payload`; payload fields are untrusted. Commit ownership must be enforced by the caller and later by an authenticated GitHub App-backed dispatcher. The worker does not accept shell instructions.

**CI status:** `repository_dispatch` returns an accepted request, **not** a completed result. Do not make a caller's required `CI` check depend on this request until a result callback/check-run integration is implemented. The existing `ocpp-csms` self-hosted workflow should remain active through that migration.

## Local validation

```bash
python3 -m unittest discover -s tests -v
python3 -m gway_remote --help
python3 -m gway_remote run system-health
```

## Next migration steps

1. Verify `system-health` against the runner in this repo.
2. Implement authenticated cross-repo result delivery and maintain the existing consolidated CI contract.
3. Switch the `ocpp-csms` runner registration and simulator workflow after end-to-end validation.
4. Add separate approval and privilege boundaries for staging/deploying to a live appliance.

## LCD Sound deployment

The `arthexis/gway-lcd-sound` main-branch push workflow sends a `lcd-sound-deploy` dispatch using `GWAY_REMOTE_DISPATCH_TOKEN` (Actions: write on this repository). The hosted authorization job verifies the SHA equals the current LCD Sound `main` tip. The Gway-001 runner then checks out that exact SHA in a disposable directory, runs `pytest`, invokes `scripts/deploy/install.sh install --no-restart`, verifies the installation, and restarts only an already-running shadow observer. It never enables the observer or turns on live notifications.

Prerequisites on the runner: user `arthe` (same home and user systemd manager as the installation), `git`, `python3`, `pytest`, and functioning `systemctl --user`. Do not merge the caller workflow until the remote task has been verified. A failed install attempts to restore the previous release; after a successful install, use `bash scripts/deploy/install.sh rollback --no-restart` from the checked-out LCD Sound repository if a runtime regression requires rollback, then restart the shadow service explicitly.

**Note:** The caller's dispatch job confirms submission, not deployment success. Inspect the corresponding Gway Remote Actions run for the final result; do not treat a successful dispatch as a successful installation.

## Local appliance status

Run `python3 -m gway_remote status` or `python3 -m gway_remote status --json`.
These commands inspect local installation attempts and read-only health checks.
They do not require GitHub credentials or modify services.

For a system-wide command, run `sh scripts/install-cli.sh` from a trusted
checkout. It installs a self-contained Python executable at
`/usr/local/bin/gway-remote`, using sudo if necessary. Afterwards use
`gway-remote status` from any working directory.

This is a local command, not a network client. Run it on Gway-001 as the
same OS user that performs installations, since the journal is under
`~/.local/state/gway-remote/attempts.json`. Global installation is
opt-in and does not activate automatic deployments.

Attempted SHA is not evidence of the installed revision. Health is measured
separately, and interrupted attempts are not automatically retried.

## Installation logs and GitHub Actions artifacts

Best-effort batch installations capture each component's installer stdout and
stderr in a private file under `~/.local/state/gway-remote/logs/`. The
journal records the log filename even if installation fails. Inspect logs
from the same OS account as the deployment runner:

```sh
gway-remote logs
gway-remote logs ocpp-csms
gway-remote logs ocpp-simulator --lines 100
```

The listing command shows recent log filenames. Add `--lines` to display
the latest matching log. Output is sanitized for common credential patterns.
The original private logs can still contain sensitive information; do not
publish them directly.

The **Appliance report and manual batch** GitHub Actions workflow is opt-in
and restricted to the repository owner. Select `report` for read-only
status inspection or explicitly select `deploy` to run the one-shot batch.
The workflow publishes a Markdown summary and a 14-day artifact containing
`status.json`, `summary.json`, `summary.md`, and bounded, sanitized
installation logs. It does not automatically run on a merge or a push.

To produce the same artifact files locally:

```sh
gway-remote report-bundle --output /tmp/gway-remote-report
```

Only the most recent journaled log for each component is exported. Export
redaction is best-effort; review artifacts before sharing outside trusted
GitHub repository access. No production deployment or automatic trigger is
enabled by these reporting commands.

## Automatic polling

The appliance report workflow polls every five minutes on the default branch, but automatic deployment is disabled unless the repository variable `GWAY_REMOTE_AUTO_ENABLED` equals `true`. Keep this unset until field validation. The application enforces the shared 20-minute quiet period and one attempt per revision. Scheduled polling never runs from a PR branch.

## Ansible CLI provisioning (opt-in)

The Ansible role installs only the system-wide `gway-remote` executable
and verifies its read-only JSON status. It does **not** enable automatic
deployments, install the three component applications, or restart services.

From the repository checkout, with a trusted inventory containing a
`gway_remote` host group and a configured SSH connection:

```sh
ansible-playbook -i /path/to/inventory ansible/playbook.yml
```

The role defaults to the runner account `arthe` and installation root
`/opt/gway-remote`. Override `gway_remote_runner_user` if necessary.
The CLI reads the attempt journal in that account's home directory.

Before activating scheduled deployment, verify the runner account, read-only
report artifacts, global CLI, cross-repository read token, and live-charge
protection on Gway-001. Leave `GWAY_REMOTE_AUTO_ENABLED` unset until
that field validation is complete.
