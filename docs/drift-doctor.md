# Phase D — `gway-remote doctor` (read-only drift evidence)

**Issue #549.** This command compares local evidence without touching production.
It does **not** mutate git, install packages, invoke Ansible, deploy providers,
restart/enable/disable systemd units, open remote SSH, fetch GitHub, issue
tokens, call MCP tools, modify enrollment, or read private credentials.

```sh
# On the machine whose installed state should be inspected:
gway-remote doctor --json

# Optional operator-selected checkout, where HEAD should be local main:
gway-remote doctor --checkout /path/to/trusted/local/gway-remote --json
```

The standalone `doctor` command is distinct from the existing
`gway-remote diagnose`, `node doctor`, and `mcp provider check`.

## Evidence sources and limits

- **Git:** If explicitly supplied, the CLI only runs fixed read-only local
  `git rev-parse`, `symbolic-ref`, `remote get-url` and `show HEAD:<fixed path>`
  commands. It checks a full SHA, `main`, and an allowed repository origin.
  It never performs `fetch`, `pull` or `status`. A local checkout is a
  **local comparison**, **not authenticated proof of current GitHub main**,
  clean working tree, accepted CI, or latest remote revision. With no checkout,
  `GIT_SOURCE_UNKNOWN` and `SOURCE_RULES_UNKNOWN` remain explicit.
- **Inventory:** The existing `/etc/gway-remote/deployment.yml` is examined
  through a bounded, non-following file descriptor anchored to its trusted
  parent. The doctor compares its SHA-256 **content digest** with the bytes
  of the exact same `ansible/inventory/deployment.yml` file in the operator's
  selected Git HEAD. It does not print repository allowlists, private paths
  or inventory file contents. Difference means `DRIFT_INVENTORY`, tagged
  `local_checkout_only`. No automatic inventory replacement.
- **MCP release:** The existing `/opt/gway-mcp/current` symlink must point
  exactly to `releases/<40-hex>`; the release and manifest must be trusted,
  contain the matching revision, and the `run.py` digest must match the
  immutable release manifest. State `selected_partial_verified` proves
  only the selected pointer, release metadata and launcher digest; it does
  **not** verify all release files, process code mapping, OAuth operation or
  service health. If it differs from the **local** Git HEAD, report
  `DRIFT_RELEASE` with that evidence boundary.
- **Provider manifests:** Reuse the sole node-owned, root-protected
  `/etc/gway-mcp-providers` discovery contract. Report only source names,
  declared revisions and historical deployment receipt status via the
  existing read-only broker `status`. `receipt=succeeded` is not an
  installed revision or a fresh working node result. Unknown or inaccessible
  manifests remain unknown; do not create a secondary provider registry.
- **systemd:** Run only fixed read-only `systemctl show` queries against
  approved service names. For gway-001, inspect the existing user MCP service
  only under the `arthe` identity; for a candidate pre-provisioned
  Watchtower, inspect its gateway/link system units. Do **not** label other
  satellites as Watchtower just because they are not gway-001. Observe the
  retired `gway-remote-watch.{timer,service}` and
  `gway-remote-deploy.service`; an active or enabled retired unit is
  `DRIFT_RETIRED_UNIT`. A missing unit in an identified role is
  `MISSING_REQUIRED_UNIT`. A systemd `active` result does **not** prove
  healthy runtime or SHA.
- **Reactivation rules:** Inspect only four pinned, checked-in Ansible
  YAML files from the operator-selected Git HEAD. A bounded static scan
  flags explicit systemd tasks that start/enable known retired unit names as
  `DRIFT_REACTIVATION_RULE`. Templated/included/dynamic tasks cannot be
  fully proved absent by this scan; source correctness is `unknown` without
  the operator checkout. **No Ansible task is executed.**

## Interpretation

`result.findings` contains only stable `code`, `status`,
`evidence` and an enumerated **proposed action for operator review**.
No repair script, shell fragment, credential, request body, raw stderr,
file contents or exception string is emitted.

`drift_detected` means a reported local mismatch or retired unit/rule;
`incomplete` means some required evidence remains unknown;
`no_observed_drift_not_health_verified` means **no checked difference was
found**, not a guarantee of parity with remote GitHub or a healthy service.

The command exits **1** if drift is detected, **2** for incomplete or unsafe
input, **0** only when no findings exist. Exit 0 does **not** certify active
OAuth, authenticated worker results, CI status, enrollment, installed
provider release, or service readiness. It never schedules remediation.

## Reconciliation workflow (manual approval separate)

1. Obtain the actual reviewed GitHub `main` SHA and CI evidence using
   existing GitHub tooling; compare with the **local** checkout SHA and
   understand its provenance.
2. Execute `doctor` with read-only access on the **specific host**, using
   the existing operator account, and keep unexpected/unknown evidence
   visible.
3. Review proposed actions and the applicable Ansible recipe before any
   opt-in or change. Do not treat the output as approval to deploy or repair.
4. Validate after a future, separately authorized deployment by comparing
   actual installed SHA and the existing authenticated runtime probes. A
   checkpointed historical receipt or revision marker never suffices.

The phase-D PR and CI exercise **only offline disposable fixtures**. No
actual systemd unit, SSH endpoint, OAuth credential, watchtower release or
provider was changed during implementation.
