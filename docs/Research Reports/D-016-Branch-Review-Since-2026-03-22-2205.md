D-016 Branch Review Since 2026-03-22 22:05

Status: Discovery Report
Created: 2026-03-26
Scope: Branch review for `feature/video-secondary-motion-pr-236` since 2026-03-22 22:05 local time
Risk Level: HIGH (runtime stability, test trust, roadmap/document drift)

---

## 1. Problem Statement

This discovery reviews all branch commits since 2026-03-22 22:05, compares the
resulting work against the current v2.6 architecture and roadmap intent, checks
document housekeeping, runs representative regression suites, and identifies the
highest-value next steps.

The branch has seen both substantial feature delivery and substantial live
debugging. The core question is no longer whether progress happened, but whether
the resulting branch state is:

- architecturally aligned
- operationally stable
- test-trustworthy
- document-harmonized
- close to the intended video / ComfyUI / secondary-motion finish line

---

## 2. Commit Window Reviewed

Reviewed commits since 2026-03-22 22:05:

- `336a01f` testing work
- `5fd6f20` PR-LEARN-262
- `4a2e1f0` PR-264
- `49300f9` PR-VIDEO-240
- `3bb4195` PR-241B
- `69cdab4` 241C
- `22f55a2` working on UI/UX
- `b69a083` PR-UX-266
- `6150d35` PR-UX-271
- `e5281a8` Vae issues
- `643e645` Work for PR-UX and fixing adetailer stage with NaNs
- `889c5ba` GUI Work PR 272 and 273
- `c1f8238` PR-UX-274

Reference base used during review:

- `af30895` docs: align PR-VIDEO-242 and PR-VIDEO-243 queue mapping

Important review note:

- the branch also has a dirty worktree at review time, including active GUI/UX
  work and uncommitted `PR-UX-275` / `PR-UX-276` artifacts
- findings below explicitly distinguish committed-branch issues from current
  uncommitted worktree state where possible

---

## 3. Architectural Alignment Summary

### 3.1 What still aligns

The reviewed branch still largely respects the v2.6 canonical execution model:

`PromptPack -> Builder Pipeline -> NormalizedJobRecord -> Queue -> Runner -> History -> Learning`

The controller, runner, and result-contract tests that exercise the canonical
execution path passed during this review, which is strong evidence that the
branch has not introduced a competing job path.

Relevant evidence:

- `tests/controller/test_core_run_path_v2.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_result_contract_v26.py`
- `tests/learning/test_learning_hooks_pipeline_runner.py`

### 3.2 Where the branch drifted

The most important recent architectural/runtime drift was not a new job path.
It was a stage-execution instability in ADetailer caused by the newer
request-local `sd_model` / `sd_vae` pinning path. Live validation on this
branch showed the older global-switch ADetailer path remained materially more
stable under A1111.

That does not violate the top-level architecture, but it does violate the
runtime-stability intent of the executor layer and must be treated as a real
branch regression.

---

## 4. Real Regressions

### 4.1 Full pytest collection is currently broken

Severity: High

`pytest --collect-only -q` fails because two test modules share the same module
basename:

- [tests/refinement/test_prompt_intent_analyzer.py](/c:/Users/rob/projects/StableNew/tests/refinement/test_prompt_intent_analyzer.py)
- [tests/unit/test_prompt_intent_analyzer.py](/c:/Users/rob/projects/StableNew/tests/unit/test_prompt_intent_analyzer.py)

This is a real suite-hygiene regression. It is not a stale architecture test.
It blocks trustworthy full-suite runs and should be fixed before any claim of
branch readiness.

Observed error:

- imported module `test_prompt_intent_analyzer` from the refinement path
  mismatches the collection target in the unit path

### 4.2 ADetailer request-local model/VAE pinning regressed runtime stability

Severity: High

During live runtime validation on this branch, repeated ADetailer NaN failures
were reproduced across multiple SDXL checkpoints and both explicit-VAE and
automatic-VAE cases. The highest-signal experiment was:

- Phase 1: disable request-local ADetailer model/VAE pinning and use the old
  global-switch path

Result:

- repeated failing ADetailer jobs started producing outputs successfully

This strongly implicates the request-local ADetailer pinning path as the main
runtime regression candidate in the reviewed branch window.

Relevant code and behavior:

- [src/pipeline/executor.py](/c:/Users/rob/projects/StableNew/src/pipeline/executor.py#L3019)
- [src/pipeline/executor.py](/c:/Users/rob/projects/StableNew/src/pipeline/executor.py#L3108)
- [src/config/app_config.py](/c:/Users/rob/projects/StableNew/src/config/app_config.py#L597)

Current review-state nuance:

- the dirty worktree now defaults ADetailer back to the global-switch path
- that mitigation appears correct based on live testing
- but until it is landed cleanly and reviewed, the committed branch history
  still contains the regression window

### 4.3 Runtime/user-state files are mixed into feature-review scope

Severity: Medium

The reviewed commit range includes mutable runtime or user-state artifacts such
as:

- [data/webui_cache.json](/c:/Users/rob/projects/StableNew/data/webui_cache.json)
- [packs/A A A.json](/c:/Users/rob/projects/StableNew/packs/A%20A%20A.json)
- [packs/A new prompt CLIP focused.json](/c:/Users/rob/projects/StableNew/packs/A%20new%20prompt%20CLIP%20focused.json)
- [state/sidebar_state.json](/c:/Users/rob/projects/StableNew/state/sidebar_state.json)

This is a real review-quality problem. It makes branch diffs noisier, increases
the chance of unintentional product-state coupling, and weakens code review.

---

## 5. Stale Tests / Expected Test Updates

### 5.1 Pipeline tab row-weight assertion is stale

Severity: Low

The current failure in
[tests/gui_v2/test_pipeline_tab_layout_v2.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_pipeline_tab_layout_v2.py#L42)
asserts that `pipeline_tab.rowconfigure(0)["weight"] == 1`.

But the current layout implementation intentionally uses:

- [src/gui/views/pipeline_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/pipeline_tab_frame_v2.py#L68)
- [src/gui/views/pipeline_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/pipeline_tab_frame_v2.py#L69)

That code gives:

- row 0 weight 0 for the overview/header surface
- row 1 weight 1 for the actual three-column content area

This is a stale assertion against an older layout contract, not evidence that
the current GUI layout is broken.

Action:

- update the test to assert the current intentional row structure
- do not revert the layout just to satisfy this assertion

---

## 6. Docs Mismatch / Housekeeping Gaps

### 6.1 `StableNew Roadmap v2.6` is internally contradictory on video status

Severity: High

The roadmap summary still says:

- [docs/StableNew Roadmap v2.6.md:60](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md#L60)
- [docs/StableNew Roadmap v2.6.md:62](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md#L62)

That text says secondary motion has foundation and SVD-native path, but
“AnimateDiff and workflow-video rollout remain queued”.

The same roadmap later marks these as completed:

- [docs/StableNew Roadmap v2.6.md:696](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md#L696)
- [docs/StableNew Roadmap v2.6.md:716](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md#L716)
- [docs/StableNew Roadmap v2.6.md:738](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md#L738)

And later instructs readers to treat them as completed:

- [docs/StableNew Roadmap v2.6.md:790](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md#L790)

This is a real canonical-doc harmonization failure.

### 6.2 The superseded video mapping doc is correct, but the roadmap was not harmonized to match

The superseded mapping note correctly states current repo truth:

- [docs/archive/reference/VIDEO_AND_SECONDARY_MOTION_REMAINING_WORK_SEQUENCE_v2.6.md](/c:/Users/rob/projects/StableNew/docs/archive/reference/VIDEO_AND_SECONDARY_MOTION_REMAINING_WORK_SEQUENCE_v2.6.md#L23)

That document is explicitly marked superseded and correctly points back to the
canonical queue. The issue is not that this mapping doc exists. The issue is
that the canonical roadmap summary was not fully updated after the video PRs
were completed.

### 6.3 Active UX tranche housekeeping is not complete in the working tree

At review time, the working tree contains uncommitted UX/doc artifacts:

- [docs/CompletedPR/PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep.md](/c:/Users/rob/projects/StableNew/docs/CompletedPR/PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep.md)
- [docs/CompletedPR/PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep.md](/c:/Users/rob/projects/StableNew/docs/CompletedPR/PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep.md)

That is not a committed-branch defect by itself, but it does mean the current
local branch state is not yet doc-harmonized.

---

## 7. Regression Test Evidence

### 7.1 Passed targeted suites

Video / secondary motion:

- `pytest tests/pipeline/test_animatediff_runtime.py tests/pipeline/test_animatediff_secondary_motion_runtime.py tests/video/test_comfy_workflow_backend.py tests/video/test_video_backend_registry.py tests/video/test_svd_secondary_motion_integration.py tests/video/test_svd_runner.py -q`
- result: `21 passed`

Learning / prompt optimization / review metadata:

- `pytest tests/pipeline/test_executor_prompt_optimizer.py tests/unit/test_prompt_optimizer_orchestrator.py tests/unit/test_stage_policy_engine.py tests/learning/test_learning_record_builder.py tests/learning/test_recommendation_engine_secondary_motion.py tests/learning/test_learning_runner_stubs.py -q`
- result: `21 passed`

- `pytest tests/review/test_metadata_contract_schemas.py tests/review/test_review_metadata_service.py tests/review/test_artifact_metadata_inspector.py tests/gui_v2/test_learning_tab_state_persistence.py tests/gui_v2/test_reprocess_panel_v2.py -q`
- result: `32 passed, 1 skipped`

Core canonical run path:

- `pytest tests/controller/test_core_run_path_v2.py tests/pipeline/test_pipeline_runner.py tests/pipeline/test_result_contract_v26.py tests/learning/test_learning_hooks_pipeline_runner.py -q`
- result: `37 passed`

GUI targeted sweeps:

- `pytest tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_tab_overview_panels_v2.py tests/gui_v2/test_pipeline_view_contracts.py -q`
- result: `16 passed, 1 skipped`

- `pytest tests/gui_v2/test_theme_v2.py tests/gui_v2/test_dialog_theme_v2.py tests/gui_v2/test_main_window_smoke_v2.py -q`
- result: `4 passed, 2 skipped`

### 7.2 Failed targeted or broad checks

Collection:

- `pytest --collect-only -q`
- result: `2833 collected / 1 error`
- classification: real regression

GUI layout batch:

- `pytest tests/gui_v2/test_pipeline_tab_layout_v2.py tests/gui_v2/test_window_layout_normalization_v2.py tests/gui_v2/test_stage_card_layout_resilience_v2.py -q`
- result: `1 failed, 3 passed, 1 skipped`
- classification: stale assertion, not a product regression

---

## 8. Readiness Assessment

### 8.1 AnimateDiff as its own pipeline stage

Status: Close at test/integration level, but not fully proven by this review in
live end-to-end runtime.

Evidence:

- [tests/pipeline/test_animatediff_secondary_motion_runtime.py](/c:/Users/rob/projects/StableNew/tests/pipeline/test_animatediff_secondary_motion_runtime.py#L16)
- [tests/pipeline/test_animatediff_runtime.py](/c:/Users/rob/projects/StableNew/tests/pipeline/test_animatediff_runtime.py)

Assessment:

- stage-level contract and fallback behavior look healthy
- shared secondary-motion integration into AnimateDiff is covered
- missing evidence gap is a fresh managed end-to-end runtime validation in the
  live app after the recent ADetailer / executor churn

### 8.2 ComfyUI flow

Status: Strong at mocked integration level, not fully re-proven here as a live
managed runtime.

Evidence:

- [tests/video/test_comfy_workflow_backend.py](/c:/Users/rob/projects/StableNew/tests/video/test_comfy_workflow_backend.py#L9)
- `Comfy workflow backend`, `video backend registry`, and related health checks
  passed in this review

Assessment:

- backend contract, manifesting, and replay-oriented behavior look good
- main remaining confidence gap is live managed Comfy runtime verification

### 8.3 Secondary motion functionality

Status: Structurally strong.

Evidence:

- SVD-native secondary motion integration tests passed
- backend registry tests passed
- secondary-motion summaries and manifests are exercised in targeted suites

Assessment:

- the shared secondary-motion layer appears substantially implemented and green
- the major remaining risk is not core feature absence; it is downstream runtime
  validation and documentation clarity

### 8.4 Learning module

Status: Structurally healthy in reviewed scope.

Evidence:

- learning runner stub tests passed
- learning record builder passed
- review metadata and inspector tests passed

Assessment:

- current reviewed work looks aligned with the learning/review direction

### 8.5 Prompt optimization

Status: Healthy in reviewed scope.

Evidence:

- prompt optimizer executor and orchestrator tests passed
- stage policy engine tests passed

Assessment:

- no major red flags surfaced in this review

### 8.6 UI / UX fixes

Status: Productively advancing, but not yet fully harmonized.

Evidence:

- several targeted GUI suites passed
- one stale layout assertion remains
- active local PR-UX-275 / PR-UX-276 work is still uncommitted

Assessment:

- UI/UX work is moving in the right direction
- the main problem is cleanup discipline and finishing the tranche coherently

---

## 9. Next PR Candidates

### Candidate 1: Test Suite Hygiene Recovery

Highest immediate value.

Scope:

- resolve the duplicate `test_prompt_intent_analyzer.py` module-name collision
- restore successful `pytest --collect-only`
- sweep for other same-basename test collisions if present

Why first:

- it restores trust in the test surface for every subsequent PR

### Candidate 2: ADetailer Stability Closure

Highest runtime value.

Scope:

- formalize the ADetailer default-global-switch model/VAE path
- keep request-local ADetailer pinning opt-in only
- retain the improved ADetailer diagnostics and non-restart behavior for
  deterministic `NansException` failures

Why second:

- it resolves the most serious live runtime regression uncovered in this review

### Candidate 3: Canonical Roadmap Harmonization

Highest documentation value.

Scope:

- fix contradictory status language in `docs/StableNew Roadmap v2.6.md`
- align summary/status prose with completed `PR-VIDEO-239` through `PR-VIDEO-241`
- verify queue-order docs say the same thing

Why third:

- current roadmap contradictions make planning and review materially harder

### Candidate 4: End-to-End Video Runtime Verification

Highest confidence-building value.

Scope:

- perform one managed AnimateDiff stage run with secondary motion enabled
- perform one managed Comfy workflow-video run
- record outcomes in a concise runtime verification note

Why fourth:

- the branch is close enough that runtime proof is now more valuable than more
  speculative refactor work

### Candidate 5: UX Tranche Cleanup and Commit Discipline

Scope:

- finish or discard the active local `PR-UX-275` / `PR-UX-276` work cleanly
- update stale layout tests to the new contract
- stop mixing user-state/cache/pack mutations into feature PRs unless explicitly
  intended

---

## 10. Recommended Order

Recommended execution order:

1. Test suite hygiene recovery
2. ADetailer stability closure
3. Canonical roadmap harmonization
4. End-to-end video runtime verification
5. UX tranche cleanup and commit-discipline pass

Reasoning:

- items 1 and 2 directly improve branch safety
- item 3 removes planning ambiguity
- item 4 gives the missing runtime proof for the branch’s major video claims
- item 5 is valuable, but lower leverage until the branch is test-trustworthy
  and the runtime path is stable

---

## 11. Bottom Line

This branch is materially closer to a functioning video / secondary-motion /
learning / review product than the top-level roadmap summary currently admits.

The biggest remaining problems are not missing feature foundations. They are:

- one real full-suite test-collection regression
- one real ADetailer runtime regression that now appears mitigated in the
  working tree
- canonical roadmap/document drift
- ongoing PR hygiene noise from mutable runtime/user-state files

The highest-value next move is not another broad feature tranche. It is to
stabilize and clean the branch so the already-delivered work can be trusted.

---

End of D-016 Discovery Report
