# Watchtower enrollment: staged internal modularization

Scope: `arthexis/gway-remote` issue #641. **Refactor only**; retain exact
HTTP routes, SQLite schema/migrations, transaction boundaries, error mapping,
snapshot/rollback behavior, and import paths. No new service, ledger, actor,
host key, grant or runtime dependency.

Stages (separate commits with reviewable boundaries):
- **0**: expand hermetic parity tests for transaction states, read-only SQLite,
  exact peer rendering and HTTP status. Existing tests under `tests/bootstrap`
  and `tests/deployment` continue to run in required CI jobs.
- **1**: move SQL schema, Enrollment value object, errors, invitation/session
  handling and Ledger into `watchtower_enrollment_ledger.py`.
- **2**: move peer-rendering, WireGuard adapter and ordered Provisioner into
  `watchtower_enrollment_provisioner.py`. Preserve single config lock,
  durable backup, fail-forward replay, and no removal of an unrelated peer.
- **3**: move `make_handler` and `serve` into
  `watchtower_enrollment_http.py`. Preserve loopback-only, read-only mode,
  no-store headers, public-safe errors and static client artifact path.

`watchtower_enrollment.py` remains the **public compatibility façade**
exporting all historical class and function names to CLI, third-party code and
tests. `wireguard_satellite.py` stays standalone: it is distributed as
`client.py` and cannot import internal modules. No data migration is required.

Deferred **behavioral** findings, intentionally not hidden in this refactor:
- `complete_bootstrap` should reject expired sessions even when an active peer
  exists. Current code validates revocation but not expiration at completion.
- A final `wg show` during successful HTTP response construction can fail
  after the ledger commit; add fault-injection and address in a distinct PR.
- Validate permissions and symlink handling around pre-existing lock/backup
  paths; do not introduce a new locking or rollback mechanism.

Field acceptance: tests and PR CI first; deploy **only** by the existing
controlled main workflow after acceptance. No action on gway-002/gway-005.
