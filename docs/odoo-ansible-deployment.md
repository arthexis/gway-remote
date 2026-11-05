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
