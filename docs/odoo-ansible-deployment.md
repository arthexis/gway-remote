# Odoo Gelectriic CLI: managed GWay Remote deployment

On **gway-001 only**, the existing `gway-remote` `deploy.sh` Ansible role
also converges the pre-provisioned `arthexis/odoo-gelectriic` repository.

- Requires `~/Repos/odoo-gelectriic`, owned by the GWay runner, clean and
  on `main`. Its update uses `git pull --ff-only origin main` as that
  unprivileged user. No checkout creation, force-reset or merge commit.
- Copies the eight command-line entrypoints into
  `/opt/odoo-gelectriic/bin/` as **root-owned mode 0755** executables.
- Publishes stable links under `/usr/local/bin/`: `odoo-gelectriic`,
  `odoo-domain`, `odoo-query`, `odoo-bom`, `odoo-credentials`,
  `odoo-quotation`, `odoo-quotation-write`, `odoo-quotation-pdf`.
  Existing unrelated commands or symlink targets are never overwritten.
- The GWay mobile Odoo adapter now invokes the root-owned binaries at
  `/opt/odoo-gelectriic/bin`, not files editable under an operator's
  personal checkout.
- Existing Odoo Bastion secrets and passphrase continue to be resolved
  by the *invoking operator's* home. Ansible never reads, generates, prints
  or changes those secrets.
- The system install is separate from `odoo-gelectriic`'s existing
  local-user `ansible/playbooks/install-cli.yml` symlink playbook. No
  additional service or Ansible role in the Odoo repository is needed.

Deployment:
```sh
cd ~/Repos/gway-remote
git pull --ff-only
./deploy.sh
/usr/local/bin/odoo-gelectriic --help
/usr/local/bin/odoo-quotation-pdf --help
```

The GWay workflow automatically executes the same play on reviewed
`main` pushes. Only the previously approved controller's inventory
receives `odoo-gelectriic`; production and quality nodes remain excluded.

As before, Odoo's own HTTPS credentials and customer records are not
validated by this role: it verifies only that the command-line tools can
start without accessing private data. Live Odoo authentication and PDF
checks should use existing operator-controlled commands.

## Unified catalog CLI

After the companion Odoo CLI change merges, Ansible installs the generic
`odoo-catalog` helper as a root-owned binary under `/opt/odoo-gelectriic/bin`.
No customer or estimate CSV is installed by Ansible; business data is passed
at runtime from separate, operator-controlled files.

```sh
odoo-gelectriic catalog inspect
odoo-gelectriic catalog validate --manifest /private/estimate.csv --uom-map /private/units.json --partner-id ID --goods-category-id ID --service-category-id ID --pricelist-id ID --tax-id ID
odoo-gelectriic catalog apply --manifest /private/estimate.csv --uom-map /private/units.json --partner-id ID --goods-category-id ID --service-category-id ID --pricelist-id ID --tax-id ID --marker UNIQUE-DRAFT-KEY
```

The existing Odoo authentication and ACLs are unchanged. No Odoo write
occurs unless `apply` is explicitly selected. The legacy helper entrypoints
remain installed for the Android adapter until its consumers migrate.


## Repository-owned deployment broker (PR #539; not activated)

Watchtower validates an authenticated execute principal, a current attested
node, immutable commit SHA and a durable request ID before dispatch.
`manual_deploy_broker.prepare_repository_owned_deploy` reserves a
non-replayable receipt; `dispatch_prepared_repository_deploy` requires a
pinned transport and rechecks node enrollment before sending a constrained
`repository_deploy` envelope (repository, SHA, request ID, node only).
Unknown delivery remains unknown; never redispatch it automatically.

The node forced-command protocol currently **rejects** deployment even
after registry validation. This is intentional: the root-owned Odoo wrapper,
local Ansible provisioning and atomic installed-release receipt have not yet
been implemented or installed. A future node executor must reserve the
request ID *before* invoking the fixed wrapper and must prove installed
revision from the Odoo release manifest and current link, not merely from
checkout HEAD. The wrapper must use Odoo's own `deploy.sh`, never copy
Ansible tasks into GWay Remote, and must not fetch arbitrary branches.

A deployment is not eligible merely because the Watchtower registry exists.
The node must independently validate its protected registration, fixed
entrypoint, node identity and installed release. The old Odoo systemd
unit must not be restored. PR #538 remains independent and read-only.


### Actual Odoo deploy.sh contract audited (PR #539)

Odoo `deploy.sh` **takes zero arguments**, refuses UID 0, requires
`ansible-playbook`, uses a per-operator flock and insists on a clean
`main` checkout for the healthy fast path. It invokes
`ansible/deploy.yml` as the invoking operator; that playbook owns the
privileged release installation. The release installer is
`scripts/deploy-cli.py`; its `is-installed --revision SHA` checks active
release integrity, not merely the checkout revision. A generic root
wrapper passing SHA to `deploy.sh` would be incorrect.

`scripts/gway-repository-deploy-odoo-gelectriic.py` is an **uninstalled**
non-root adapter. It checks exact checkout SHA, clean main and fixed
`deploy.sh`, invokes it without arguments, then requires
`deploy-cli.py is-installed --revision SHA`. The checkout path in this
pilot is a design placeholder; no production path is asserted. Ansible
provisioning and authenticated operator binding are not yet approved.
This adapter does not publish an installed receipt or authorize a remote
request. Its output is not a substitute for independent release proof.
