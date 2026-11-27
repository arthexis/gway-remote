# Protected Android delivery transition (#749, #753, #656)

Status: review-only; **do not merge until candidate 798 is either published under separate owner authorization or explicitly superseded by the owner**. This plan is not a change to branch rules, executable workflows, publication admission, or lab configuration.

## Frozen candidate

- Source: 84a71f0d9ace3cb5b65aa8f6963c4389925a2c37
- Tree: 8b3e5b8f74e30b0b7a628e6224252d6926be586d
- Version: 798 / 0.2.798
- Signed artifact: 15226479572; APK SHA-256 a7296f82f6efc9705d0132a67849d623e0f39991df9c970712b9023426396815
- Full acceptance: 46058181279, artifact 15227023769; CI 46039258806, Compose 46039311028
- #718 remains held; no signing, installation, rebuild, publication or credential changes.
- Main effective ruleset 24802372: strict CI context (integration 15368), PR, deletion and non-fast-forward protections. Do not change it during freeze.

## Promotion sequencing (separate future owner authorization)

The current android_rc_promotion.validate_revision requires main to match the candidate source or exactly one direct commit removing only the literal ANDROID_PUBLICATION_HOLD_718 marker from android.yml, and rejects the marker while present. No other main changes, including this plan, may be merged before exact promotion. A PLAN_ONLY dispatch skips the job; it is not a preflight. Preserve the accepted receipt and immutable artifact; do not create a draft release or tag now.

After explicitly authorized hold removal, reconcile main, private ledger, artifact identity, acceptance provenance, latest version, and conflicts using reviewed promotion validator. Dispatch workflow 432321883 with exact source/tree/version/digest/acceptance_run and PUBLISH_EXACT_ACCEPTED_APK only on explicit authorization. Verify independently downloaded APK hash and unchanged signer, tag target, release identity and ledger publication receipt. No overwrite, rebuild, downgrade or retry on uncertain mutation. Do not close release-tracked issues before independent verification.

## Replacement automation after publication

1. Rebase this work on then-current protected main. Retain strict CI and all existing protections. Replace legacy android_release_gate publish-dependent accept path with an always-reporting premerge classifier that does not publish, sign, install or execute PR code on a lab host. Use reviewed base code and complete changed-file evidence. Unknown/truncated evidence fails closed. Android-relevant changes require exact head/base CI and hosted Android/Compose proof; non-Android changes report not applicable only when classification is complete. Avoid treating a premerge test APK as a distribution candidate.
2. Preserve separate owner-controlled integrated-main allocation/sign/install/accept/promotion gates, monotonic ledger, durable receipts, shared physical lease, at-most-once dispatch, immutable artifact and signing isolation. Physical acceptance is a release gate after protected merge; never silently waive a current protection. Do not arm auto-merge unless explicit same-repository owner opt-in and exact head/base/check identities are revalidated immediately before arming. Publication is separate from merge and cannot be inferred from green CI.
3. Test candidate-aware classifier and negative cases below before enabling any new required context. Demonstrate always-reporting checks on representative PRs, record source and integration ID, then add the replacement context while keeping existing strict CI. Verify branch rules by readback and a controlled PR; never reduce protections or use bypass. If unavailable or ambiguous, leave current rules unchanged. Do not enable auto-merge or change rules without separate reviewed activation.
4. Replace legacy release closure with explicit allowlisted release-tracked issues and independent release verification; preserve unrelated open issues, #718 policy and superseded PR evidence. Closure must be idempotent and conditional on the exact published artifact and tag. No GitHub closing keywords for release-tracked changes.
5. Retire optional legacy polling timer permanently under #656; no new timer, opt-in marker or recurring installation. The manual legacy test path remains isolated for historical evidence until separately reviewed removal. On gway-001 the matching user/system timer inventory was empty on 2026-11-27 (read-only request 79820261127000000000000000000002). Hosted hermetic tests and candidate physical acceptance replace legacy automated distribution; no lab package uninstall or reset.

## Required negative/positive acceptance matrix

| Case | Expected result |
|---|---|
| Non-Android fully classified change | Always-reporting N/A, strict CI remains required |
| Android change, exact CI + Compose evidence | Premerge gate passes only for exact head/base |
| Missing, stale, incomplete, forged or failed CI/Compose evidence | Fail closed; no merge |
| Changed head/base or concurrent merge | Re-evaluate; no stale auto-merge |
| No owner opt-in / fork / untrusted principal | No auto-merge, signing or physical dispatch |
| Concurrent hardware request / expired lease / duplicate dispatch | No second install or acceptance |
| Stale candidate / main advances / wrong signer / expired artifact | Refuse promotion |
| #718 held / no explicit publication authorization | No release or tag mutation |
| Wrong tag, release conflict, wrong download digest or missing receipt | Fail closed; no closure |
| Exact published receipt verified twice | Idempotent closure of allowlisted issues only |
| Legacy timer absent | No activation; preserve current phone and credentials |

Rollback: disable only newly staged automation after owner-reviewed incident decision, preserve strict CI, existing admission controls and immutable ledger. For Android releases, forward-fix with increasing version and same signer; no uninstall, downgrade, credential transfer or destructive reset.

This document is a proposed transition and acceptance matrix, not evidence that replacement implementation, tests or ruleset activation have occurred.
