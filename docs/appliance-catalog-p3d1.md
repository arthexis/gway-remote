# #565 P3-D1 — explicit checked catalog snapshot seam for pure attempt policy

The optional keyword-only `catalog_targets` argument of
`attempt_policy.plan()` accepts a tuple of ordered, reviewed
`(target_id, repository)` pairs. It is **not** an authorization grant.
The default caller path and return values remain unchanged.

A caller may obtain `load_catalog().targets`, explicitly project to an
immutable tuple of `(id, repository)`, and pass it into the policy. The
caller alone performs resource I/O and parity checks. The pure policy
requires the injected snapshot be an **exact, ordered tuple equal** to the
existing reviewed `reconcile.TARGETS`, otherwise returns
`Plan("blocked", (), "catalog differs from reviewed target registry")`.
No unknown, duplicate, differently ordered, renamed or extra repository
can become a candidate, including ocpp-simulator.

No operational caller is switched to the new argument. The optional
`managed` filter remains separate and unchanged: no policy or node
may acquire permissions from this metadata. All CI/quiet/attempt
conditions, result ordering, failure conditions and return contracts
remain intact. The function has no file/process/network I/O.

This is an intentionally small, opt-in *interface* increment only.
`reconcile.reconcile` and `appliance_watch`, including journal,
reservation, cooldown, locks, GitHub workflow and `apply=True` paths,
remain untouched until an independent security and integration gate.
Ansible/root-owned deployment allowlists, owner installers, probes
and MCP provider manifests remain authoritative and independent.

Hermetic unit tests cover legacy output parity, managed/deny-all,
unknown/duplicate/drifted descriptor rejection, fail-closed before any
candidate iteration, no file/subprocess I/O, idempotent attempts, CI and
cooldown. Rollback: revert these three files. Keep #565 open.
