# GWay Remote operator commands

This is the current operator entry point. Run registration commands **on Watchtower** with `sudo`. This document describes the current implementation, not planned features.

## Generate a satellite bootstrap URL

```sh
sudo gway-remote register ocpp-abb-1
sudo gway-remote register status
sudo gway-remote register revoke <session-id>
```

`register` reads the root-owned `/etc/gway-remote/watchtower.json` settings (override with `--settings PATH`). It generates a short-lived HTTPS bearer bootstrap URL and prints a command of the form `curl -fsSL '<bootstrap-url>' | sudo sh`. The default validity is 15 minutes; `--minutes N` accepts 1–60. `--replace` authorizes replacing an existing registration; `--repair` is for host-identity repair. Do not use these flags for a fresh host.

**Keep the generated URL private.** It is a bearer credential; do not paste it into issues, chats, logs, or screenshots. Run the printed command on the intended new host after verifying its OS, existing WireGuard configuration, and trusted HTTPS origin. See [satellite bootstrap](wireguard-satellite-bootstrap.md).

**Node names:** registration accepts existing `gway-NNN` IDs and lowercase hyphenated host IDs such as `ocpp-abb-1`. The same validator is used by enrollment and attestation. Use the actual intended host identity; do not invent an alias.

## Low-level Watchtower administration

`gway-remote watchtower` is the lower-level administrative interface; it is **not** the preferred shortcut for issuing bootstrap URLs. It accepts an action and explicit infrastructure settings. For example:

```sh
sudo gway-remote watchtower register --device gway-006 \
  --ledger <ledger-path> --network <approved-cidr> --gateway <gateway-ip> \
  --public-url https://register.gelectriic.com
```

The low-level `watchtower invite` action issues an invitation record, **not** the ready-to-run bootstrap URL. Use the top-level `register` command when Watchtower's operator settings are provisioned. Other actions include `status`, `bootstrap-status`, `revoke-bootstrap`, `adopt` and `attest`; inspect `gway-remote watchtower --help` for their required arguments. Never guess ledger/network/gateway values from examples.

## Enrollment is not deployment authorization

A registered WireGuard node is not automatically an Ansible deployment target or an MCP executor. The canonical deployment inventory is `ansible/inventory/deployment.yml`; its `remote_managed_repositories` list controls repository scope. An empty list denies writes. The current inventory has `customer.gelectriic.com` with an empty list, **not** a ready-to-deploy `ocpp-reports` target. The current `deployment_policy.require_local_deployment` also limits local appliance writes to `gway-001`.

For the intended customer host, the proposed identity is `ocpp-abb-1` and DNS name `customer.gelectriic.com`. Naming support is implemented in this PR. Do not enable deployment until Ansible targeting and an `ocpp-reports`-only authorization path have been implemented and validated. A `deploy --all` must never bypass that restriction.

## Where to look

- [Satellite bootstrap](wireguard-satellite-bootstrap.md): one-time URL lifecycle, bootstrap execution, and safety
- [WireGuard enrollment](wireguard-enrollment.md): protocol history and design; some sections describe **proposed**, not implemented, functionality
- [Watchtower automatic deployment](watchtower-auto-deploy.md): **GWay Remote MCP backend** deployment to Watchtower; not an OCPP Reports customer deployment guide
- `gway_remote/__main__.py`: current CLI parser and operator command implementation
- `gway_remote/wireguard_enrollment_contract.py`: current accepted node identifier syntax
- `ansible/inventory/deployment.yml`: current management inventory and repository allowlists
