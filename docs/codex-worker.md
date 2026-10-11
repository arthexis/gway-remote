# Codex worker — chunk 1 foundation

This is an **idle-only** persistent worker. It does not accept tasks, launch
Codex, inspect credentials, modify repositories, or expose a network port.
The next chunk will define a trusted task queue and isolated worktrees.

## GWAY-001 manual opt-in validation

Codex CLI is expected to be installed already. Verify `command -v codex`
under the intended service account. Do not print authentication tokens.

From the checked-out PR branch, run:

```sh
python3 -m unittest discover -s tests -v
python3 -m gway_remote.codex_worker --help
```

The service file assumes the package is importable by system Python. **Check
that first** using `/usr/bin/python3 -c 'import gway_remote.codex_worker'`.
If it is not importable, install/provision the code through the existing
GWAY Remote installer or adjust the service's ExecStart to the verified
installed module location before starting. Do not point systemd at a mutable
development checkout.

For an opt-in user service install, copy the unit to
`~/.config/systemd/user/gway-codex-worker.service`, then run
`systemctl --user daemon-reload` and
`systemctl --user enable --now gway-codex-worker.service`.
Verify `systemctl --user status gway-codex-worker.service` and
`python3 -m gway_remote.codex_worker status`. The status must show
`state: idle` and `task_execution_enabled: false`.
If persistence across logout is required, the operator may separately
consider `loginctl enable-linger` after reviewing the service account.

Stop with `systemctl --user disable --now gway-codex-worker.service`.
No remote task execution is enabled by this change.
