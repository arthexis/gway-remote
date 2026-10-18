# Local GitHub Health collection (Gway-001)

This is the **evidence collection** increment of issue #144, not the complete
Pass A/Pass B alert classifier. It replaces neither the current ChatGPT alert
lifecycle nor its historical baseline yet.

The module `python3 -m gway_remote.github_health_watch` uses **GET-only**
GitHub REST requests for the exact five allowlisted repositories. It records
the current open-PR list size and recent workflow-run failure evidence, writes
one SQLite observation per repository, and atomically publishes the API
snapshot. It does not dispatch workflows, repair PRs, or deploy software.

**Important:** `alerts: []` currently means **classification not yet
implemented**, NOT "all clear". The next increment must implement durable
alert episodes, persistence thresholds, equivalent-run baselines, and
explicit classification coverage in the API/Android UI before operational
health can be reported. Do not disable the existing ChatGPT watch yet.

The unit files under `systemd/` are user-service templates. They are not
installed or enabled by this PR. Ansible deployment, environment-file
provisioning and service-account executable paths require separate validation.
The service needs a read-only `GITHUB_TOKEN` configured privately in
`~/.config/gway-remote/github-health.env`; never commit credentials.
The same file can set `GWAY_REMOTE_GITHUB_HEALTH_SNAPSHOT` and
`GWAY_REMOTE_GITHUB_HEALTH_DB`. The API process must be configured to read
the identical snapshot path. Install and enable only after deployment tests
verify the Python environment and systemd user service.

For a manual local smoke test in the installed Python environment:

```sh
python3 -m unittest tests.mobile.test_github_health_watch
python3 -m gway_remote.github_health_watch
```

Network failure or incomplete repository evidence fails the collection;
the prior snapshot is not overwritten and eventually becomes stale.

## Appliance deployment (Ansible increment)

Ansible installs system units from `deploy/systemd/gway-remote-health.*`.
The collector uses the deployed source at `/opt/gway-remote`, with the system
Python interpreter, and stores SQLite/snapshots in
`/home/arthe/.local/state/gway-remote/`. No commit-hash venv is used by
this CLI deployment; it is a Python zipapp/source installation.

The hourly timer is **disabled until** an operator provisions
`/home/arthe/.config/gway-remote/github-health.env` privately, with
permissions `0600` and owner `arthe`, containing a read-only token:

```sh
GITHUB_TOKEN=github_pat_REPLACE_WITH_READ_ONLY_TOKEN
```

Do not commit the file or paste the token into CI logs. Re-run `deploy.sh`
after provisioning to enable the timer. Ansible does not create credentials.
The API defaults to the same snapshot under its runtime user's home; when
the API runs under a different account, configure
`GWAY_REMOTE_GITHUB_HEALTH_SNAPSHOT` explicitly.

Check `systemctl status gway-remote-health.timer` and
`journalctl -u gway-remote-health.service` on the appliance. This is
still partial classification; leave the ChatGPT health watch enabled.
