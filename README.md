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

## Trigger appliance deployment from Gway-001

Use the globally installed CLI to request the existing GitHub **Appliance Deploy**
workflow (this command does not install anything locally):

```sh
gway-remote deploy --all             # all components
gway-remote deploy                    # error: explicit target required
gway-remote deploy ocpp-csms         # one component
gway-remote deploy ocpp-reports
gway-remote deploy gway-ap-kiosk
gway-remote deploy reports          # ocpp-reports
gway-remote deploy sound            # gway-lcd-sound
gway-remote deploy ocpp             # all approved ocpp-* repositories
gway-remote deploy gway             # all approved gway-* repositories
```

The CLI requires the GitHub CLI (`gh`) installed and authenticated as an
account authorized to dispatch workflows in `arthexis/gway-remote`.
Use `gh auth login`, or provide `GH_TOKEN` / `GITHUB_TOKEN` with
Actions write permission. GitHub's workflow also checks that the actor is
`arthexis`; a different authenticated user can submit the request but
the workflow will not run deployment jobs. The command targets `main` and uses the workflow's approved deployment targets.\nA shorthand matches complete hyphen-separated words, even when intermediate\nwords are omitted. Every matching approved target receives its own deployment\nrequest in catalog order; no match fails without dispatching. Future approved\nentries are included automatically. `--all` still selects the entire approved\ncatalog, not arbitrary GitHub repositories.

A successful command indicates only that GitHub accepted the request.
Inspect the Actions workflow run to determine installation success.

## Inspect configured deployments

```sh
gway-remote deployments
gway-remote deployments ocpp-csms
gway-remote deployments --json
```

This read-only inventory lists the six configured repositories, last recorded
deployment attempt timestamp, attempt result, attempted SHA, current GitHub
`main` SHA, and independently verified installed SHA. An installed revision
is shown as `unknown` when no supported release link can verify it; a
successful attempt alone is **not** proof of installation. The timestamp
represents the last attempt state update, not necessarily its start time.
GitHub access is required to read the latest main revisions. The journal
keeps only the most recent attempt per target, not a full history.

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

The **Appliance Report** workflow is a strictly read-only, owner-dispatched
snapshot. The separate **Appliance Deploy** workflow permits explicit manual
installation, bypassing only the quiet period; a five-minute scheduled poll
runs automatically on the default branch. Both workflows publish
a Markdown summary and a 14-day artifact containing
`status.json`, `summary.json`, `summary.md`, and bounded, sanitized
installation logs. The report workflow never runs an installer.

To produce the same artifact files locally:

```sh
gway-remote report-bundle --output /tmp/gway-remote-report
```

Only the most recent journaled log for each component is exported. Export
redaction is best-effort; review artifacts before sharing outside trusted
GitHub repository access. No production deployment or automatic trigger is
enabled by these reporting commands.

## Automatic polling

The **Appliance Deploy** workflow polls every five minutes on the default branch without an enable variable. Automatic batches enforce the shared quiet period and one attempt per revision; an explicit manual invocation bypasses only the quiet period, not CI, SHA verification, or the deployment lock. Scheduled polling never runs from a PR branch.

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

Verify the runner account, read-only report artifacts, global CLI,
cross-repository read token, and live-charge protection on Gway-001.
Scheduled deployment is enabled by default; CI, quiet-period, and deployment
safety checks remain in force.

## Automatic GWay Remote backend installation

After **Python checks** succeeds for a push to `main`, the **Deploy GWay Remote backend** workflow runs on the `gway-001` self-hosted runner. It verifies that the tested SHA is still the current main tip, runs unit tests again on the appliance, installs the versioned source into the system-wide `/usr/local/bin/gway-remote` zipapp, and verifies the installed CLI status schema. Superseded runs skip installation. The workflow shares the appliance concurrency group so batch deployments do not overlap.

This updates the **GWay Remote CLI/backend package**, not other repositories (CSMS, LCD Sound, or simulator), and restarts the existing mobile API user service after installation, using its explicit user-bus context. A bounded authenticated health probe must succeed; otherwise the workflow attempts rollback. The runner must have permission to install the CLI (including configured noninteractive sudo if required). Failed validation prevents installation; installation or verification failures fail the workflow rather than claiming success.

Android APK publishing remains a separate workflow. For changes requiring both server and APK, coordinate readiness via the two workflow outcomes rather than assuming that a successful APK build implies the server has been updated.

### Remaining development and verification gates

The CLI-only deployment in PR #44 is **not** a complete mobile API rollout. Finish the following in order before treating a main merge as deployed:

1. **Read-only Gway-001 reconnaissance (local agent).** Identify the real API listener and process/service manager, executable and working directory, OS account, TLS ingress, health endpoint, runner identity, install permissions, and rollback options. Do not create or replace services based on assumptions.
2. **Define a single deployment owner and source of truth.** Confirm whether the existing systemd unit executes the installed zipapp or a checkout/venv. Avoid a second service, duplicate deployment mechanism, or accidental restart of an unrelated component.
3. **Preflight and install transaction.** Verify the tested main SHA, required privileges, available disk space, and health baseline. Stage the backend safely, preserve the previous working artifact, and make the switch reversible. Never report success merely because copying files succeeded.
4. **Controlled API lifecycle.** Only if reconnaissance confirms the correct existing unit, restart or reload it after installation and wait for a bounded authenticated/local health probe. Confirm the process serves the newly deployed revision, not merely that the port responds. On failure, restore the previous artifact and restart it; surface an explicit failed deployment if recovery cannot be verified.
5. **Test deployment behavior.** Cover no service, insufficient permissions, stale SHA, failing unit, failing health probe, rollback, concurrency with appliance jobs, and idempotent redeploys. Run a Gway-001 dry run before automatic restarts are enabled.
6. **Coordinate Android publication (PR #43).** Require verified backend compatibility/readiness before publishing an APK that depends on changed API commands. Keep Android version codes monotonic, signing identity stable, and the release immutable. A successful APK build alone is not evidence of backend readiness.
7. **End-to-end acceptance.** Merge a controlled revision, verify backend SHA and mobile API health on Gway-001, verify the signed GitHub Release and its in-app update metadata, then exercise the phone against the updated API. Document rollback for both sides.

Automatic restart is implemented in the deployment workflow. It requires a configured GWAY_REMOTE_API_TOKEN Actions secret and a successful on-device deployment check; APK release gating remains a separate concern.

### Explicit failed deployment retry

In **Appliance Deploy**, select `retry_failed=true` when deliberately
retrying a revision whose last recorded attempt failed. Manual dispatch
invokes `deploy-batch --now --retry-failed`, bypassing the quiet period and
releasing **failed** attempt records for the current main SHA only. It never
retries successful or interrupted records, never weakens CI/current-main/lock
checks, and does not affect scheduled polling. An ordinary manual deploy
continues to respect one attempt per SHA.

Appliance reports show **Attempted SHA** (journal) separately from **Installed
SHA** (read independently from a versioned release symlink when available).
Unknown means the current installed revision cannot be verified, notably for
the simulator. Do not infer the installed revision from an attempt, even if
that attempt is marked installed.

## Agent Ops appliance deployment

The appliance batch includes `arthexis/gway-agent-ops` as a fourth trusted repository. Manual `Appliance Deploy` calls `deploy-batch --now` and can install a green, merged Agent Ops main revision. The installer verifies the exact Git SHA, creates an isolated versioned Python environment under `~/.local/share/gway-agent-ops/releases/`, checks `agent --help`, and atomically updates `~/.local/bin/agent`. It does **not** adopt Codex credentials, execute GitHub issues, or start a daemon. `--now` bypasses only the quiet period, not SHA/CI verification or one-attempt policy. A separate Remote-to-Agent Ops interface and field verification are required before the mobile surface can assign the LCD Sound test issue.
