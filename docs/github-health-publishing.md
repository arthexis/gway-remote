# Publishing hourly GitHub Health Watch results

The watch producer runs **outside** GWay Remote. This repository does not
schedule, poll, or execute the watch. The publisher only accepts a fully
completed snapshot (schema v1 in `docs/github-health-watch.md`) and atomically
places it where the authenticated mobile API reads it.

On the GWay-001 host, configure the API process environment:

```sh
GWAY_REMOTE_GITHUB_HEALTH_SNAPSHOT=/home/arthe/.local/state/gway-remote/github-health.json
```

After each successful external watch, explicitly transfer its completed JSON
file to the host and invoke:

```sh
python3 -m gway_remote.github_health_publish \
  --source /path/to/completed-watch.json \
  --destination /home/arthe/.local/state/gway-remote/github-health.json
```

Run as the API service account; destination permissions are 0600. The producer
must provide the five allowlisted repositories, both completed diagnostic
passes for each, and its own durable ACTIVE/RESOLVED lifecycle ledger.
Do **not** generate an empty-success snapshot on producer errors. Invalid,
partial, stale or out-of-scope inputs fail without replacing the previous file.
The API independently rejects stale snapshots after two hours.

**Not yet wired:** There is no verified transport from the existing hourly
watch's execution environment to Gway-001. Until that transport and API
environment configuration are established, Android correctly displays
`unavailable`. Do not claim this PR enables live watch results.
