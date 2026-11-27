# GWay Browser provider — opt-in Reports canary

This increment adds a node-owned MCP stdio provider and a Firefox WebExtension.
The existing federation authenticates requests and classifies status/snapshot as
read, and click/scenario_run as execute. No new OAuth or public endpoint.

## Threat boundary

The first release is intentionally not a general browser automation service.
The operator grants one active tab at the exact root-configured HTTPS origin
by clicking the extension toolbar button. The badge says ON during a lease of
at most ten minutes. Click again, switch tabs, close the tab, navigate outside
the supported Reports routes, disconnect or timeout to revoke. The grant is
to the existing authorized GWay clients, not to an individual OAuth principal.
Do not grant it on a sensitive account/tenant unless that delegation is intended.
The local bridge accepts only the desktop/executor UID via a protected Unix
socket in /run/user; it is not a new privilege boundary against that same UID.

Only dashboard, RFID history and charger detail pages are supported.
Snapshot returns opaque, single-use 30-second references, static control
kinds and aggregate UI evidence. No DOM text, raw URLs, customer identifiers,
cookies, password fields, profile data, storage, arbitrary JS, network fetches
or screenshots are returned. Native host validates every result against
a closed schema. No broad host permissions, debugger ports, or HTTP listener.
No generic fill, keyboard, mouse or arbitrary click capability. Links are
checked against a fixed same-origin route/query policy; Heartbeat expansion
and the reviewed pagination button are the only non-link actions. Browser
permission refusal must never be worked around.

## Canary installation

Use a clean, CI-validated exact checkout on gway-001. Set the real origin via
operator configuration (not source code). Run as the existing installer user
with the usual Ansible privilege escalation:

    ansible-playbook -i localhost, -c local ansible/playbooks/browser-provider.yml \
      -e gway_browser_authorize=true \
      -e gway_browser_revision=FULL_VALIDATED_COMMIT \
      -e gway_browser_origin=https://reports.example.test

The playbook stages only pinned browser files under /opt/gway-browser and
registers the native host and provider in the existing system registries.
It does not restart the browser, modify its profile, change any OCPP service,
or install an extension. The native host and MCP executable are pinned to the
same revision. There is no automatic appliance deployment of this provider.

For development acceptance, the operator may use Firefox's standard
about:debugging > This Firefox > Load Temporary Add-on workflow, selecting
/opt/gway-browser/FULL_VALIDATED_COMMIT/firefox/manifest.json. This is
explicit developer-mode installation by the browser owner, not remote
profile modification; the temporary add-on disappears when Firefox restarts.
For durable use, package these exact reviewed files into an XPI and obtain
normal Firefox signing/installation approval. Never disable signature checks.
If Firefox or the platform refuses an action, stop and report the blocker.

Open an existing authorized Reports session, click the extension toolbar
button and verify ON. Refresh MCP discovery. Use the exact node gway-001.

## Acceptance (read-only operations, no charge commands)

1. Before granting: status/snapshot unavailable. Wrong origin and login
   pages denied. Verify no browser-side connection survives tab switch.
2. Dashboard snapshot: RFID summary row count and session row count,
   operator admin panel hidden; choose one returned rfid_history ref.
3. click with the selected ref; inspect a new snapshot after navigation.
   Assert page=rfid, history_chart=true, session_rows>0; choose rfid_next
   if present, verify history_page increments. Replay of the old ref fails.
4. Return to the dashboard manually and select the intended charger through
   a reviewed charger_detail ref (or manually open the known charger).
   Inspect snapshot; select a heartbeat_expand ref. Snapshot again after
   data loads. Assert loaded_events=50 and response_id_header=true. Select
   heartbeat_next, then verify 100 and subsequent pages if present.
   scenario_run only chooses a unique matching control; otherwise explicitly
   select a reference. Never interpret action_started/navigation_started as
   verified success. Use fresh snapshots and do not replay uncertain actions.
5. Verify gway:read rejects click/scenario_run; gway:execute permits the
   reviewed read-only UI actions. Revoke lease. Confirm socket cleanup.
6. Admin-only view, tenant isolation, actual mobile/desktop visual checks
   and precise API status remain separate acceptance requirements.

No screenshot publication, credential changes, browser security changes,
production deployment, AgentOps, or Android publication (#718) in this work.
