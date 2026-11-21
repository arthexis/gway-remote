# Bootstrap regression suite

This directory is the **pytest-owned** home for the previously ungrouped
root-level bootstrap, WireGuard enrollment, host identity, host trust and
recovery tests. CI runs every `test_*.py` in this directory as its own job.

`tests/deployment/` retains tests of Ansible, offline provisioning and its
isolated rollback harness; `tests/core/` retains executor identity and
runtime unit contracts. These continue to run in their existing CI jobs.
Do not move the special Ansible 2.12 isolated tests without updating their
explicit `unittest discover` job.

Shared fakes use **only** temporary fixtures and in-memory WireGuard state.
The `ledger` fixture creates a new SQLite file per test. No node,
Watchtower, private key, network admission, sshd or systemd is contacted.

## Implementation boundaries

- `gway_remote/bootstrap_script.py`: pure server-side shell renderer, called
  by the existing HTTP handler. Its output and host-guard ordering must remain
  unchanged except by an explicit behavior PR.
- `gway_remote/watchtower_enrollment.py`: HTTP handler, enrollment transaction
  ledger and WireGuard provisioner. A future nonfunctional split can separate
  the ledger and provisioner **after** behavior and import compatibility are
  secured; avoid mixing that extraction with #641's protocol changes.
- `gway_remote/wireguard_satellite.py`: **intentionally standalone** Python
  artifact downloaded as `client.py`; do not split it into package imports.
  The remote shell must run with only standard library and declared OS tools.

These tests prove code-level parity, not that a new node is fully bootstrapped:
#641 still requires end-to-end receipt, trust pin, central grant, and canary
acceptance. Keep `gway-002` and `gway-005` out of this refactor.
