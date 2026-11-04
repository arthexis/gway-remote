# Android v2 — Stage A: navigation simplification (issue #378)

Stage A is deliberately presentation-only. MCP handles routine detailed operations, while the existing Android app remains useful for glanceable status, deployments, exceptional Agent Ops tasks, and recovery when only the phone is available.

| Existing Android feature | Placement | Disposition |
| --- | --- | --- |
| System (status and health) | Home | Keep |
| Deployments | Home | Keep |
| Assigned Issues (Agent Ops) | Home | Keep as exceptional workflow |
| GitHub Health | Home | Keep as concise read-only CI view |
| CSMS | More tools | Retain until MCP replacement is accepted |
| Benchmark | More tools | Retain, not a primary mobile workflow |
| Notifications (LCD / Sound) | More tools | Retain hardware diagnostics |
| App update | More tools and settings | Retain recovery/update ability |
| Internal API health, status, CSMS details, LCD, Sound, agent assignments | Existing internal panels | Unchanged and still accessible to existing callers |
| MCP access / bearer token | Not yet exposed | Stage B–D: server-verified WebAuthn/passkey issuance only |

**Interaction:** with a blank search, show only the four home entries; `More tools and settings` expands or collapses the secondary features. When a user enters a filter, search covers *all* registered visible features, including the secondary tools. Closing an already-open panel does not depend on menu grouping. Extra actions outside the registry retain their existing behavior.

**Safety:** This change does not alter any operation IDs, command dispatch, execution policies, authentication, service endpoints, Agent Ops admission or backend functionality. It does not introduce a dummy bearer token button or local-only biometric gate. Existing operation registry entries and deep/internal panel IDs remain stable.

**Acceptance:** Android CI unit/build, new grouping/search contracts, physical Android navigation smoke test (home, expand, search, opened panel, Agent Ops, app update). Feature removal and code deletion are deferred to Stage E.
