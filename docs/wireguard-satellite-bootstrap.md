# Satellite WireGuard enrollment with GWAY Remote

GWAY Remote owns both the private operator registration CLI on Watchtower and the standalone satellite WireGuard client. Neither uses the deprecated classic GWAY sampler.

## Watchtower operator

The production Watchtower Ansible role installs `/etc/gway-remote/watchtower.json` (root-only mode 0600) and the `gway-remote` CLI alias, but remains inert until approved #228 activation. The settings reference the **same SQLite ledger, allocation CIDR, and tunnel gateway** as the running Watchtower enrollment owner. Do not invent or default those values.

After #228 R3 cutover has been validated:

```sh
sudo gway-remote register gway-004
# prints ONE sensitive https://register.gelectriic.com/v1/bootstrap/<opaque> URL

sudo gway-remote register status
sudo gway-remote register revoke <session-id>
```

The bearer URL is **as sensitive as an invitation**. Do not paste the live URL into GitHub, logs, issues, chat, screenshots, or shared tickets. It is node-bound, expires within 1–60 minutes (15 by default), and becomes unusable after the satellite confirms activation. The operator can revoke the session ID at any time. The underlying invitation token never appears in the URL, scripts, argv, or logs and only hashed tokens are persisted.

## Fresh satellite

On a newly imaged, explicitly authorized Debian/Raspberry Pi OS satellite that has HTTPS/TLS reachability to the approved registration hostname:

```sh
curl -fsSL "<bootstrap-url>" | sudo sh
```

The short HTTPS-delivered script verifies root, installs Python 3, curl, and WireGuard tools using apt, fetches the self-contained satellite client from the **same versioned HTTPS bootstrap origin**, creates the satellite private key locally, enrolls via `/v1/enroll`, atomically installs root-only `/etc/wireguard/gway.conf`, enables `wg-quick@gway`, and acknowledges successful local startup. It uses only the Watchtower's validated tunnel gateway `/32` as `AllowedIPs`, never an Internet default route.

The client refuses to overwrite unmanaged WireGuard configs or take over an already active `gway` interface with no matching config. An interrupted attempt preserves a root-only `.pending-key` so the same authorized session and device key can resume. If the URL expires during an interrupted install, a new operator-issued session for the same device can be used; never manually rotate the pending key as an attempted recovery. If state is ambiguous, stop and inspect rather than deleting peers/configuration.

The old interactive standalone flow remains available for controlled manual diagnostics when its trusted server key and invitation are provided via protected means.

## Security boundaries

- The URL is an HTTPS bearer capability. Application request logging and the exact Nginx bootstrap path must both suppress **request targets and secret-bearing values**. The route includes `Cache-Control: no-store`; no public invitation issuance or administration endpoints exist.
- **First-stage trust:** `curl | sudo sh` authenticates the remote script only via the TLS origin and local OS CA store. The hub public key provided by the HTTPS script does **not** constitute an independent out-of-band pin. A genuinely independent signing key or preprovisioned certificate pin would have to be installed on the satellite beforehand to strengthen this trust boundary.
- Watchtower `register.gelectriic.com` HTTPS delivery and the WireGuard UDP endpoint `register.gelectriic.com:51820` are logically separate. Public UDP reachability is proven only by an external handshake.
- Do not restart the Watchtower `gway` interface, renumber or delete existing peers, or disturb gway-001. There is no automated global rollback; retries move the owned operation forward, while ambiguities block.
- The deployment role stages Nginx routes but does not silently turn on public routing. A field agent must verify the effective Nginx configuration and ensure **one** enrollment owner during the gated #228 rollout.

## Acceptance and operator receipt

PR #254 covers code/tests only; merge readiness requires passing PR CI including offline session, HTTP, client, Nginx and deployment checks. #228 separately owns the approved Watchtower deployment and real gway-004 test. Confirm the exact installed SHA, sanitized peer counts, service state, successful fresh external handshake and tunnel reachability, session replay refusal, and continued gway-001 operation. Do not close #228 or claim rollout complete from tests alone.

## Repair-first recovery and post-operation verification (#636)

Use the existing node-bound bootstrap URL and its existing `--repair` purpose
for an enrolled node with a matching managed WireGuard configuration. Repair
does not select or migrate the node executor account, change the WireGuard
peer, override SSH trust, or confer a deployment permission. It attempts the
authorized repair immediately rather than rejecting it because of an unrelated
executor-account comparison. Fresh enrollment retains its non-root installer
gate, and conflicting/unmanaged tunnel state remains a hard stop.

The downloadable client's failure result is a **sanitized category**, not
the exception message (which could contain bearer URL or key material).
`invitation` calls for checking the protected URL/session;
`tunnel_identity_or_config` calls for checking owned configuration and
server/host identities; `enrollment_or_service` points to enrollment/service
response; `local_command` points to the failed local tool; and
`executor_provisioning` concerns only a new install or its executor
preparation. Investigate the indicated stage **after the failure**, rather
than requiring every identity to match before an authorized repair.

A local bootstrap success proves only that the local tunnel is configured,
its interface public key agrees, and any requested enrollment repair was
acknowledged. It **does not** prove the Watchtower-to-node SSH or MCP
execution path. The operational acceptance performed separately by an
authorized operator must check the existing strict-pinned SSH `limits`
protocol through Watchtower and, if allowed, one fresh correlated
`node_exec` / `node_result` terminal receipt. Diagnose an SSH failure
there (host-key trust, authentication, selected receiver identity, or protocol
version) without treating `already_attested` or `execute_available`
as successful execution. Never retry an uncertain command with the same ID.

For gway-002, preserve its production inventory and empty
`remote_managed_repositories` list. This procedure grants no permission to
apply changes on Watchtower or gway-002.
