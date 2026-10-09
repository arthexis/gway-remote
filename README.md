# gway-remote

Central job dispatcher and managed runner workloads for `gway-001`.

## Design

Personal-account repositories trigger **repository_dispatch** on this repository. Only this repository schedules the self-hosted runner. The source repository never needs direct access to that runner. There is no organization requirement.

The initial job catalog is deliberately narrow:

- `system-health`: read-only environment diagnostics
- `ocpp-simulator`: isolated OCPP simulator smoke test at a pinned commit from `arthexis/ocpp-csms`
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
