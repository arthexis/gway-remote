# Protected Android delivery transition (#749)

Supersedes the implementation staging in review-only #789, whose historical design remains intact. This change is an advisory first stage; it does not activate rules, auto-merge, issue closure, or any candidate workflow.

## Baseline and sequencing

- Candidate 798 source 84a71f0d9ace3cb5b65aa8f6963c4389925a2c37, tree 8b3e5b8f74e30b0b7a628e6224252d6926be586d, accepted run 46058181279. Its signed artifact and receipt remain immutable. Backend merges superseded its direct promotion eligibility. Do not allocate a successor while release work remains unconsolidated.
- Integrated base c8fa056f7b953283b4745c65c48a12f9ddf69fed. #718 publication hold remains. Existing strict CI (integration 15368) remains required.
- The new advisory context is Android candidate readiness, distinct from the legacy Android acceptance context. Legacy workflows cannot satisfy the new context. Hosted PR checks are not signed release candidate acceptance.
- The new workflow is hosted only, checks out trusted current main, uses bounded complete file and workflow listings, matches exact PR head/base and workflow IDs, checks the latest attempt and required job, and re-evaluates after PR changes, CI completion and main pushes. It has no device, signing, publication, merge or issue-write permissions.
- Changes to the evidence producer require separately reviewed trusted workflow transition. Fork/draft Android PRs cannot become hosted-ready. An outdated base must integrate main before Android readiness. Mixed backend changes retain ordinary protected merge and deployment behavior.
- Reconciliation runs are serialized, but GitHub can replace a pending run. Every invocation reconciles the bounded open PR set; a stale trusted checkout is rejected. Before activating the new required context, demonstrate fresh readback for actual PRs and verify that the selected GitHub status producer and strict CI cannot be substituted by a PR-authored workflow. Review stale status handling on base advancement and rerun. Do not activate the old android_acceptance_ruleset helper for this new context.
- Pure ruleset and merge preflights are provided. They add no bypass, preserve existing CI, reject non-owner, mixed or stale PRs, and return merge_armed=false. Actual owner-opt-in auto-merge orchestration remains separate: verify downstream push workflow delivery for the existing authenticated transport (GitHub Actions token merges may suppress push-triggered workflows) before enabling it. Do not grant new credentials.
- Candidate allocation, signing, installation, full authenticated acceptance and exact-artifact promotion remain separate existing native workflows and private ledger. The new readiness gate never dispatches them. Keep existing monotonic version and shared hardware admission policies. No change to hold-removal or promotion requirements.
- The published-candidate closure preflight requires the durable ledger, full acceptance, owner-authorized successful publication run, exact tag/asset/signer and independently downloaded bytes. A source-bound docs/android-release-issues.json manifest (schema 1, issues array of explicit issue numbers) must be reviewed and included in the future candidate source. #718 is excluded; it requires separate disposition. Closure remains a plan only, no issues are mutated. A later trusted owner workflow must revalidate before idempotently closing each explicitly approved issue.
- #656 legacy polling timer retired; no timer reactivation. Legacy manual test path remains historical, not a prerequisite or authorization for a distribution candidate.
- Production runtime is unaffected: exact readiness paths are in the paired non-runtime deploy-impact policy; any mixed runtime change still deploys normally.

## Remaining rollout gates

1. Validate PR CI and exact evidence-control path exclusions. Merge only reviewed workflow tooling once safe.
2. Observe actual main-hosted advisory evaluations for non-Android and Android PRs; test missing/failed/stale evidence and base changes. Resolve any status-provenance or workflow-transition blockers. Stage additive ruleset activation only after independent readback and owner approval.
3. Complete trusted opt-in merge orchestration and exact published issue closure workflow; verify no credential/protection bypass or suppressing necessary downstream workflows.
4. Consolidate residual #673 acceptance and explicit release issue mapping; allocate at most one future candidate only when authorized. #718 remains held.
