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
