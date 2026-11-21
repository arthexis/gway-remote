# Generic node bootstrap — local convergence stage (#641)

This stage runs **after** the existing, node-bound HTTPS WireGuard bootstrap,
using an immutable Git checkout whose full 40-character revision is supplied
by the reviewed Watchtower release. It reuses the same atomic package installer,
executor selection and SSH relay tasks already employed by regular Ansible.
It never creates a Watchtower grant, issues OAuth credentials, configures an
AgentOps workspace or changes remote-managed repository inventories.

Exact inputs: a local node ID matching the machine hostname, a verified
existing non-root sudo installer, a public ED25519 relay key obtained from the
existing Watchtower identity (never a new private key), an optional explicit
executor override, and a pinned revision.

The playbook refuses an unclean or wrong-revision checkout before installation.
Local readiness is deliberately **not** equated with Watchtower execution
authorization or a terminal MCP job receipt. A later stage must pin the already
attested host key on Watchtower and perform strict SSH limits, with explicit
separate grant/revoke for execution. Never replay an uncertain request.

The playbook is located in `ansible/` (rather than `ansible/playbooks/`) to
preserve the existing role task contracts using `{{ playbook_dir }}/../scripts`.
Do not run the full `gway_remote` role for a new satellite; it includes other
controller-specific provider, repository and reporting configuration.

## Central operator acceptance (not a public endpoint)

Only an authenticated root operator on Watchtower can run
`gway-remote exec grant gway-NNN`. This command validates the currently
active host key from the Watchtower enrollment ledger, requires existing
gateway private SSH material, stages the exact public pin and execute.json
under a root-only transaction journal, updates the same ledger eligibility
table and restarts the existing gateway. It then runs a **strict read-only
SSH limits check as gway-mcp-gateway**, not root. If any stage fails it
attempts byte-for-byte rollback; an uncertain crash blocks further updates
until explicit operator recovery. It creates no credentials, no new services
and does not enable deployments or providers.

`gway-remote exec revoke gway-NNN` removes the configured transport and
eligibility together, preserving the historical public pin. The command
never returns a terminal node_exec receipt; a separate authorized
`node_exec hostname` and correlated `node_result` are required for
end-to-end acceptance. Do not retry uncertain request IDs.

An unaccepted transaction can be recovered only by an administrative
`python3 -m gway_remote.watchtower_exec_eligibility recover gway-NNN`
from the installed Watchtower owner after manual journal reconciliation.
No public bootstrap token may invoke grant or recovery.
