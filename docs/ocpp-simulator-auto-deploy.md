# gway-001 OCPP simulator automatic installation, PRE-READY

## One existing runner; no new authority

GitHub returned **zero** repository runners for
`arthexis/ocpp-simulator`, while the **existing** installed runner on
`gway-001` belongs to `arthexis/gway-remote`. The runner is online,
has labels `[self-hosted,Linux,ARM64,gway-001]`, and operates as `arthe`.
The existing GWay Remote webOS TV auto-install already uses this topology.

A new **scheduled GitHub Actions workflow in GWay Remote** (not the
simulator repository) runs every ten minutes on this same runner. Scheduled
workflows belong to GWay Remote and therefore have access to its existing
repo-scoped runner. The workflow accepts no repository, node, SHA, path,
token, shell or other user-supplied execution inputs. No service, timer on
the node, runner registration, OAuth change, secret or new credential is
created. The existing operator's GitHub CLI login and Git credential helper
are reused; the operator has already demonstrated read access to the private
simulator repository, main branch, CI and git remote.

## Mandatory fail-closed admission

1. Require the exact runner user `arthe` and native `aarch64` platform.
2. Require **simulator PR #20 `merged=true`**; otherwise skip. This prevents
   installing simulator's old main when this GWay Remote PR merges first.
3. Read the literal `arthexis/ocpp-simulator` **current main** SHA.
4. Require the **latest CI workflow run for that exact SHA** to be a
   completed successful **push** run on `main`. Draft PR CI alone is
   insufficient, as is a previously successful run superseded by failure.
   Pending/failed/missing runs skip and retry next schedule. Invalid GitHub
   evidence fails closed.
5. Create a fresh temporary, private checkout, never mutating the operator's
   `~/Repos/ocpp-simulator`. Clone only the fixed GitHub URL using existing
   `gh` authentication and no stored credential writes, select the exact
   SHA, check source contract files and re-check main.
6. Skip a genuinely verified same-SHA release; if the same-SHA installed
   artifacts are corrupt, fail closed rather than silently repairing in place.
7. Run the **simulator's own** `sh ./deploy.sh` as `arthe`, with its
   existing Ansible lock and `OCPP_SIMULATOR_EXPECTED_MAIN_SHA=<sha>`. The
   simulator role checks the live GitHub main immediately before changing
   `previous/current`, builds Python/Go and the test-only UID client from
   reviewed source and **does not start simulator sessions or services**.
8. Verify exact `current`, `.revision`, expected `previous`, Python/Go
   command links and binary availability, test-only client SHA256 and pinned
   Go module provenance. Recheck main afterward. A main advance, timeout or
   verification failure produces no claimed installed success.

No new deployment receipt authority is introduced; the installed release
pointer, provenance and content hashes remain the source of truth.
No production CSMS, SQLite, port 9000, charge point, replay, admission,
CleanVerified or Watchtower changes are made by the PR.

## Important inter-repository preacceptance caveat

`arthexis/ocpp-simulator` PR Draft #20 still contains
`.github/workflows/deploy-main.yml`, scheduled for push to simulator main
on a **nonexistent simulator-scoped runner**. Before final acceptance of
simulator PR #20, retire or change that ineffective workflow in its own PR
branch, so merges do not leave indefinitely queued jobs. This GWay Remote
PR must remain Draft and not be merged until this cross-repository contract
is accepted. GWay Remote's new schedule is deliberately independent of
other appliance deployment target lists and does **not** grant broad MCP
execution/Watchtower access to simulator.

Offline tests cover exact push CI, latest-failed/pending denial, missing PR
merge denial, pointer safety and static absence of extra authority. They do
not prove live deployment; the first real installation needs separately
authorized merges and a receipt from gway-001.
