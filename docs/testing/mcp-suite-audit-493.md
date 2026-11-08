# MCP test-suite refactor #493 — final coverage and maintenance audit

## Scope and inventory (after increments A–D)

| Suite | `test_mcp*.py` files | Source lines | Coverage role |
|---|---:|---:|---|
| `tests/core` | 5 | 289 | protocol, scope, core behavior |
| `tests/infrastructure` | 13 | 572 | federation catalog, authorization, dispatch, provider isolation |
| `tests/mobile` | 22 | 2199 | gateway HTTP, OAuth, PKCE, sessions, bearer challenge, transport |
| `tests/deployment` | 6 | 370 | Ansible, manifest publication, rollback, idempotence, release guards |

Inventory counts exclude shared helpers and files without the `test_mcp` prefix. This is a *contract map*, not line coverage; CI matrix exercises other test files too. The 22 mobile files are HTTP/service tests, not necessarily Android UI tests.

## Consolidation and negative-case matrix

| Increment | Shared helper | Negative behavior preserved |
|---|---|---|
| A | `tests/helpers/mcp_federation.py` | ambiguous/destructive tools fail closed; trusted scopes |
| B | `tests/helpers/mcp_provider.py` | unknown tools, missing/timeout provider, authorization denial, wrong node |
| C | `tests/helpers/mcp_http.py` | bearer scope challenge, execute denial, OAuth PKCE/session/revocation |
| D | `tests/helpers/mcp_deployment.py` | symlink rejection, missing provider, rollback and second-run changed=0 |
| E | reuses A/B in `test_mcp_federated_catalog.py` | duplicate tool rejection, unknown tool and insufficient scope |

## Residual risks and guardrails

- `test_mcp_refactor_487_de.py` still asserts textual playbook guards. These are intentional smoke checks, **not** a substitute for the real Ansible lifecycle fixture. Prefer YAML-structured checks only if they prove the same semantics across Ansible versions.
- The lifecycle fixture asserts exact `changed` counts for its **versioned isolated fixture**, not a global number of tools or production resources; these counts are contractually meaningful.
- No `FakeFederation`, `FixtureFederation` or inline `class Transport` duplicates remain in the named MCP suites inspected. Avoid adding new ones when the existing helpers suffice.
- `tests/mobile` remains the largest MCP suite. Future simplification should be driven by observed flakiness and runtime, not by deleting security cases.
- Python test assertions do not establish live wire `tools/list` equivalence or actual production rollback. Those belong to separately authorized deployment validation.

## Timing and reproducibility

Run targeted regression: `python3 -m pytest -q tests/core/test_mcp*.py tests/infrastructure/test_mcp*.py tests/mobile/test_mcp*.py tests/deployment/test_mcp*.py` (shell expansion; use Python file discovery if a glob does not match). Record pytest's total time and CI jobs, and keep any Ansible fixture limited to temporary directories. CI jobs are the final merge gate. No production deploys are part of this issue.
