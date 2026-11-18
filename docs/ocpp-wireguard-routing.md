# OCPP lab over existing WireGuard — phased plan (#628)

**Status:** Phase 0, source-only preflight. No network configuration is changed by
this file, its helper, or their unit tests. The plan does not authorize live
Watchtower or satellite route/firewall changes.

## Architectural decision

- The **OCPP simulator on gway-001** is a WebSocket client. Its existing
  `--url` selects an approved, **isolated** CSMS on gway-004 or another quality
  node. OCPP 1.6J is application data, not GWay Remote MCP/AgentOps transport.
- First preference: directly connected private LAN **if independently reachable
  and authorized**. Otherwise reuse the existing WireGuard star via Watchtower;
  do **not** create a general node-to-node mesh or new TCP/WebSocket proxy.
- Watchtower forwards encrypted-peer traffic in the OS network stack. Each
  spoke-to-hub-to-spoke packet requires receive/decrypt, forwarding and
  encrypt/transmit, so the cost is nonzero. Do not claim negligible impact on
  Watchtower/Odoo without a measured baseline.
- A direct WireGuard 001↔004 tunnel is a **conditional fallback** if load,
  availability or latency measurements justify it, never a Phase 0 requirement.

## Verified source constraints and open evidence

- `gway_remote.wireguard_satellite` provisions a single hub-only `AllowedIPs`
  destination; existing peers must not be silently rewritten.
- `gway_remote.watchtower_enrollment` owns the managed enrollment ledger and
  Watchtower peer configuration. Extend this owner after identifying its
  **effective production** configuration, not an abandoned legacy service.
- Prior MCP reads on 2026-11-18 found active `wg-quick@gway` and `ocpp-csms`
  and listening TCP/9000 on both nodes. The kernel chose the physical default
  gateway for the other node's VPN IP; peer-to-peer routing is **not yet proven**.
  The unprivileged executor could not read runtime AllowedIPs. Watchtower
  forwarding rules, kernel IPv4 forwarding and actual CSMS isolation remain
  UNKNOWN.
- Existing management issue #264 is closed, but that does **not** prove OCPP
  data-plane connectivity or authorize broad traffic routing. Preserve the
  independent #596 legacy enrollment and #614 independent nodes tracks.

## Phase 0 read-only route preflight

Run on the **source** with the destination address obtained from the authorized
Watchtower registry (never guess it from the hostname). The command reads the
local kernel's IPv4 route only, with a three-second timeout:

```sh
python3 -m gway_remote.ocpp_wireguard_route DESTINATION_IPV4
```

It returns JSON with `schema`, `selection`, `interface`, `via_gateway`, and
`reason`. Output excludes the target IP, source IP, peer keys and full routing
table; it does not write anything. Exit 0 means a *candidate* VPN or LAN route
was identified, **not** that it works end-to-end. Exit 2 means unexpected or
indeterminate route; stop rather than attempting to fix it.

Interpretation:

| selection | Meaning | Next step |
| --- | --- | --- |
| `via_hub` | Local route selects existing interface `gway` without next-hop gateway | Inspect authorized peer AllowedIPs, hub forwarding/firewall, return path |
| `via_lan` | Local route uses direct `eth0`/`wlan0`/`wlan1`, no next-hop router | Independently check permitted LAN TCP reachability; Wi-Fi isolation may still block |
| `unexpected` | Default physical gateway, wrong interface, WG gateway or blackhole | Do not run simulator; inspect intended transport |
| `unknown` | Missing/invalid route, destination mismatch, command unavailable | Record blocker; do not infer success |

The route selector deliberately **does not** call ping, open TCP/9000,
inspect WireGuard secrets, restart interfaces or modify routes. `via_hub` does
not show that Watchtower accepts forwarded packets or that the correct peer
owns the destination. Never use a route selection to authorize execution,
enrollment, firewall changes or OCPP identities.

Separate **read-only** gates before any peer routing:
1. Confirm the approved VPN destination from Watchtower enrollment and the
   effective owner/source of both persistent and runtime AllowedIPs; inspect
   only sanitized network metadata as an authorized operator, never paste
   public/private keys or full peer configs.
2. On 004 inspect the **actual CSMS instance** and whether it is isolated from
   live charging, accounting and customer dashboards. A listening port alone
   is insufficient. Determine WS vs WSS, TLS hostname/CA and auth.
3. Confirm Watchtower IPv4 forwarding and firewall FORWARD policy (not INPUT).
   The hub must authorize **001 source → 004 destination TCP/9000 and replies**,
   with no other peers or ports. The peers must also have reciprocal WireGuard
   AllowedIPs/routing and preserved hub management reachability.
4. Check an authorized direct LAN alternative separately before routing OCPP
   through Watchtower; no assumption from matching LAN subnet alone.

## Phase 1: code-only scoped policy, then separately authorized apply

Implement deterministic, idempotent changes within existing WireGuard/Ansible
ownership. Stage the diff and negative tests. Fail closed for unknown peers,
invalid source/destination, non-/32 scopes, broadened port ranges,
default-route changes and unavailable rollback. Do not hand-edit managed peer
blocks or restart `wg-quick@gway`. Compare persistent/runtime configuration,
capture a verified protected backup and rollback procedure **before any apply**.
No activation, Watchtower firewall changes or remote CSMS connection in CI.

## Phase 2: canary acceptance

After isolated CSMS/identity approval, test route and TCP reachability separately
from WebSocket/OCPP acceptance. On gway-001 run only the explicitly approved
`SIM-*` identity using the simulator's existing `--url`; begin with
BootNotification and Heartbeats (no transactions), confirm server-side evidence,
then an expressly scoped short transaction and graceful StopTransaction.
Check disconnect behavior and continuity of other node services.

## Phase 3: measure Watchtower cost

Measure before/during/after in the **same environment**: CPU utilization /
WireGuard softirq, VPN throughput, packet loss/retransmits, OCPP handshake and
heartbeat latency, plus Odoo request latency (preferably p95). Start at one
simulator, then increase conservatively only when previous step is healthy.
Set any thresholds from observed baseline and available headroom rather than
invented throughput/CPU limits. If significant degradation is demonstrated,
evaluate direct 001↔004 WireGuard with NAT/UDP reachability, reversible config,
and explicit per-peer ACL. Preserve Watchtower as control plane.

**Do not conflate:** source/CI success, hub policy installed, locally selected
route, TCP handshake, WebSocket subprotocol negotiation, accepted BootNotification,
simulated charging, or production readiness.
