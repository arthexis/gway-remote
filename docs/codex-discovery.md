# Codex GitHub discovery

AgentOps is the sole owner of automatic GitHub issue pickup. Exact node identity
labels (for example `gway-001`) express automatic assignment, and `on-hold`
prevents automatic pickup. Explicit manual execution does not require either
label. No workflow, issue template or legacy worker should apply node labels
merely to describe a host, route a manual task or classify a finding.

The legacy GWay Remote Codex worker no longer imports GitHub issues into its
independent queue. Its compatibility discovery command only reconciles
historical GitHub-imported tasks when GitHub confirms closure, preserving
explicit manual tasks and existing decisions. Removing a label cannot revoke
a separately approved manual operation. The read-only issue list still shows
open trusted-author issues in its existing allowed repositories.

Manual inspection: `gway-remote codex discover`, `gway-remote codex tasks`,
`gway-remote codex task ID`. Do not activate the legacy worker as an automatic
pickup mechanism. No change to runner labels, device identities or credentials.
