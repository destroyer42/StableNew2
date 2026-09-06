# PR-MVP-005 - Post-Baseline Delta Disposition

Status: Completed
Priority: HIGH
Effort: MEDIUM
Phase: Phase 0 - Canon and recovery control
Date: 2026-09-05

## 2. Context & Motivation

The recovery branch `recovery/mvp-baseline` is based on
`f919cb436af2e9e703ca357e830fb57c1f60d578`, carries the approved architecture
amendment, and closed repository completeness in `PR-MVP-000`. Three later
commits contain a mixture of useful repairs, obsolete architecture
compensation, post-MVP features, generated state, and destructive content
cleanup:

- `24063b729f3f0618a9de4a40af28a62d1c553958`;
- `d452a2a8c2ac0db65039b7172c30ec373f6c0337`;
- pre-canon `1a9eb493f00b6ba7f37f0c23dd47cf235c1a2874`.

The commits are a linear sequence from `f919cb4`. This PR audits the
incremental ranges `f919cb4..24063b7`, `24063b7..d452a2a`, and
`d452a2a..1a9eb49`, so overlapping changes are not counted twice. It resolves
their disposition without merging, rebasing, or cherry-picking any of them.

The governing contracts are `docs/ARCHITECTURE_v2.6.md`,
`docs/PROMPT_PACK_LIFECYCLE_v2.6.md`, and the Finalized MVP Roadmap. Passing
tests are evidence that a patch behaves as written; they are not evidence that
the behavior belongs in the MVP architecture.

## 3. Goals & Non-Goals

### Goals

1. Account for every changed file in the three incremental commit ranges.
2. Classify each logical change as `ADOPT`, `REWRITE`, `DEFER`, or `REJECT`.
3. Record architecture rationale, observed test evidence, and the exact future
   PR that owns any MVP-relevant carry-forward.
4. Establish that no unidentified later-branch dependency blocks the contract
   migration.
5. Preserve all comparison commits and branches without accepting them
   wholesale.

### Non-goals

1. Do not modify runtime code, tests, packs, generated state, or user data.
2. Do not merge, rebase, or wholesale cherry-pick `24063b7`, `d452a2a`, or
   `1a9eb49`.
3. Do not authorize a later runtime PR merely by labeling a change `ADOPT` or
   `REWRITE` here.
4. Do not revive universal PromptPack identity, mutable NJR state, paired pack
   authority, LTX/Comfy video, or multi-character support for MVP.
5. Do not expand `PR-MVP-010` through `PR-MVP-090` beyond the active roadmap.

## 4. Guardrails

- The canonical production path remains typed intent -> compiler -> immutable
  NJR -> JobService -> queue/repository -> `PipelineRunner.run_njr` -> typed
  handler -> artifacts/history.
- PromptPack identity is required only for a PromptPack source. A fabricated
  pack ID or prompt is not a valid compatibility technique.
- GUI projections must be supplied by application/compiler services. GUI code
  must not reconcile competing draft and preview execution truths.
- Queue scheduling policy must not be implemented by temporarily mutating a
  shared `auto_run_enabled` flag.
- Generated caches, diagnostics, review state, and user-authored packs are not
  source-code patches.
- `ADOPT` means the behavior may be proposed in the named future PR with an
  exact allowlist and fresh verification. It is not permission to cherry-pick.
- `REWRITE` means the MVP requirement is retained but the historical
  implementation must not be copied forward.
- `DEFER` means the capability is outside the MVP and must remain quarantined
  or hidden; a post-MVP architecture decision is required before revival.
- `REJECT` means neither the patch nor its compatibility strategy is carried
  into the recovery line.
- NJR, queue, runner, controller, GUI, pack, and test contracts may not be
  changed by this documentation-only PR.

## 5. Allowed Files

### Files to Create

- `docs/CompletedPR/PR-MVP-005-Post-Baseline-Delta-Disposition.md`

### Files to Modify

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

### Forbidden Files

- `src/**`
- `tests/**`
- `packs/**`
- `data/**`
- `reports/**`
- `tmp_prompt_pack_probe*/**`
- every file not explicitly listed above

No Git branch merge, rebase, history rewrite, or cherry-pick is allowed in this
PR.

## 6. Implementation Plan

### Step 1 - Freeze the evidence boundary

Use the full object IDs in section 2 and audit the three incremental ranges.
The observed inventories are:

| Range | Files | Diff size |
|---|---:|---:|
| `f919cb4..24063b7` | 8 | 196 insertions, 3 deletions |
| `24063b7..d452a2a` | 20 | 1,477 insertions, 68 deletions |
| `d452a2a..1a9eb49` | 87 | 386 insertions, 12,590 deletions |

### Step 2 - Apply the approved disposition

#### `f919cb4..24063b7`

| Logical change and covered files | Disposition | Rationale and owner |
|---|---|---|
| Start WebUI with closed stdin and add bounded crash hints for CUDA OOM, upcast configuration, AnimateDiff import failure, and batch-pause output: `src/api/webui_process_manager.py`, `tests/api/test_webui_process_manager.py` | **ADOPT** | The behavior improves bounded startup failure and operator actionability without creating another execution path. `PR-MVP-060` owns the exact runtime proposal; `PR-MVP-080` may refine operator wording. |
| Clear stale queue-panel content when the queue projection is an empty list: `src/gui/panels_v2/queue_panel_v2.py`, `tests/gui_v2/test_queue_run_controls_restructure_v2.py` | **ADOPT** | Empty is a valid authoritative projection, not absence of an update. `PR-MVP-060` owns adoption in the image journey. |
| Give same-named diagnostic image metadata collision-safe artifact names: `src/utils/diagnostics_bundle_v2.py`, `tests/debughub/test_debughub_extracts_image_metadata.py` | **ADOPT** | Preserving all diagnostic evidence is architecture-neutral and release-relevant. `PR-MVP-080` owns adoption. |
| Suppress ADetailer model-drift warnings during request-local pinning: `src/pipeline/executor.py`, `tests/pipeline/test_executor_adetailer.py` | **DEFER** | ADetailer is not guaranteed in the conservative MVP image path. `PR-MVP-060` owns the decision to admit this optional stage or leave it quarantined; no earlier PR may carry the patch. |

#### `24063b7..d452a2a`

| Logical change and covered files | Disposition | Rationale and owner |
|---|---|---|
| Rebuild cached preview jobs from AppState PromptPack draft when records lack `prompt_pack_id`: `src/controller/pipeline_controller.py` and the related additions in `tests/controller/test_pipeline_preview_to_queue_v2.py` | **REJECT** | This is the exact universal-PromptPack identity compensation forbidden by canon. `PR-MVP-030` replaces the seam with typed source compilers and one authoritative preview result; it must not preserve this fallback. |
| Multi-character actor UI, broad-dict contract, prompt/job builder expansion, safe LoRA actor skipping, and feature tests: `src/gui/widgets/multi_character_selector.py`, `src/pipeline/config_contract_v26.py`, `src/pipeline/job_builder_v2.py`, `src/pipeline/prompt_pack_job_builder.py`, `src/training/lora_manager.py`, `tests/pipeline/test_prompt_pack_multi_character.py`, `tests/services/test_prompt_pack_multi_character.py` | **DEFER** | Multi-character support is outside the MVP, the widget was not integrated into the active authoring surface, and silent actor skipping weakens explicit validation. `PR-MVP-080` owns keeping the surface unavailable for MVP. Any revival requires a post-MVP roadmap amendment and a new typed-intent design; this implementation is not pre-approved. |
| Actor examples written into paired JSON/TXT pack files: `packs/A A A.*`, `packs/Beautiful_matrix_test.*`, `packs/CrazyCoolVariety.*` | **REJECT** | These are user/sample content mutations and reinforce dual native authorities. `PR-MVP-050` will curate migration fixtures explicitly and will not import these working-content edits as code. |
| Runtime/cache/review/diagnostic state: `data/webui_cache.json`, `img_a.png.review.json`, `reports/diagnostics/.diag_cooldown_queue_runner_stall.json` | **REJECT** | Machine-local mutable state must not be adopted as repository implementation. `PR-MVP-010` owns isolation and pollution guards. |
| Completion claim and stale mini-roadmap update: `docs/CompletedPR/PR-CORE-014-Multi-Character-Support.md`, `docs/PR_Backlog/CORE_TOP_20_EXECUTABLE_MINI_ROADMAP_v2.6.md` | **REJECT** | The Finalized MVP Roadmap supersedes the sequence, and the completion record overstates an unwired, deferred feature. The files remain non-authoritative historical inputs; they do not enter the active index. |

#### `d452a2a..1a9eb49`

| Logical change and covered files | Disposition | Rationale and owner |
|---|---|---|
| Delete 45 tracked files under `packs/`, including JSON, TXT, and backup material | **REJECT** | Bulk deletion risks user/sample data and bypasses conflict-reporting migration. `PR-MVP-050` owns deliberate inventory, fixture curation, backup, and one-file JSON migration. |
| Delete the five tracked `tmp_prompt_pack_probe*` trees, including caches, probe packs/presets, and a diagnostics ZIP | **ADOPT** | These 30 tracked files are test/runtime debris, not source. `PR-MVP-010` owns their exact removal together with tests that prevent repository-root pollution. |
| Return immediate acceptance from `submit_job_with_run_mode` and omit rejected IDs from `enqueue_njrs`: `src/controller/job_service.py`, `tests/pipeline/test_job_service_njr_validation.py` | **REWRITE** | Callers need truthful acceptance, but the patch is coupled to mutable `Job`, current `pack_required` validation, and pack-shaped `PipelineRunRequest`. `PR-MVP-030` owns a typed NJR submission result/policy after `PR-MVP-020` freezes the NJR contract. |
| Batch submission by temporarily disabling `JobService.auto_run_enabled`, filtering rejected jobs, restoring the flag, and calling `run_next_now`: `src/controller/pipeline_controller_services/queue_submission_service.py`, `tests/controller/test_queue_submission_service.py` | **REWRITE** | The desired guarantees are one coalesced notification, explicit acceptance, and one scheduling decision. Mutating a shared global flag creates race and exception-state risk. `PR-MVP-030` owns submission policy; `PR-MVP-040` verifies transactional queue persistence. |
| Invent a positive prompt from the source filename when an LTX video prompt is blank: `src/controller/video_workflow_controller.py`, `tests/controller/test_video_workflow_controller.py` | **REJECT** | This fabricates user intent to satisfy a broad validation seam, and LTX is outside the native-SVD-only MVP. `PR-MVP-070` defines typed SVD intent and explicit blank-prompt validation without this fallback. |
| Estimate and display image totals by introspecting broad config dictionaries in the GUI: `src/gui/preview_panel_v2.py`, `tests/gui_v2/test_preview_panel_summary_v2.py` | **REWRITE** | Showing the total is useful, but execution cardinality belongs to compiler/application projections, not GUI config heuristics. `PR-MVP-060` owns a typed preview summary and the count display. |
| Compare PromptPack IDs and row indices across cached preview jobs and JobDraft to decide which GUI truth to render: `src/gui/views/pipeline_tab_frame_v2.py`, `tests/gui_v2/test_pipeline_tab_callback_metrics_v2.py` | **REWRITE** | This compensates for competing shadow projections and again assumes pack identity. `PR-MVP-030` owns one typed compiler preview; `PR-MVP-060` consumes it in the GUI journey. |
| Treat an empty `enqueue_njrs` result as learning rejection and remap accepted IDs: `src/learning/execution_controller.py`, `tests/controller/test_learning_completion_resume_regressions.py` | **DEFER** | Learning productization is not an MVP release gate, and the surrounding code still fabricates `learning_*` PromptPack IDs. `PR-MVP-080` owns keeping automated learning submission out of the MVP surface. A post-MVP spec must rebuild it on the final `PR-MVP-030` submission contract. |

All 115 changed-file occurrences across the three incremental ranges are
covered by 17 logical slices: 4 `ADOPT`, 4 `REWRITE`, 3 `DEFER`, and 6
`REJECT`. No source or test file is approved for immediate copying.

### Step 3 - Synchronize active planning records

Update the Finalized MVP Roadmap to mark this spec approved and summarize the
binding dispositions. Add this file to Tier 4 of `docs/DOCS_INDEX_v2.6.md`.
Do not change Tier 1/Tier 2 runtime contracts because this PR changes no runtime
truth.

## 7. Testing Plan

### Unit tests

No unit-test files change in this documentation-only PR.

Historical verification was performed in three detached worktrees. Each raw
historical snapshot first failed collection with
`ModuleNotFoundError: No module named 'src.state'`. After applying only the
`PR-MVP-000` repository-completeness commit, the focused results were:

- `24063b7`: 44 passed, 2 skipped;
- `d452a2a`: 45 passed;
- `1a9eb49`: 34 passed, 1 skipped.

The runs used Python 3.10.6 and pytest 9.0.1. Pytest reported that `pytest.ini`
causes the pytest configuration in `pyproject.toml` to be ignored; that remains
`PR-MVP-010` scope.

### Integration tests

No integration test is required because no runtime patch is applied. Future
owner PRs must rerun the focused tests against their rewritten or explicitly
allowlisted implementation.

### Journey or smoke coverage

No product journey changes in this PR. The later image, video, and release PRs
retain their existing roadmap gates.

### Manual verification

Run:

```powershell
git diff --check f919cb4 24063b7
git diff --check 24063b7 d452a2a
git diff --check d452a2a 1a9eb49
git status --short --branch
```

Confirm that only the three allowed documentation files differ on
`recovery/mvp-baseline` and that no comparison branch moved.

## 8. Verification Criteria

### Success criteria

1. The three exact commit IDs and all incremental changed files are accounted
   for.
2. Every logical slice has one primary disposition and a rationale.
3. Every MVP-relevant adopt/rewrite has a named future PR owner.
4. Deferred capabilities have an MVP quarantine owner.
5. The active roadmap and docs index identify this approved specification.
6. No runtime/test/content file or comparison branch changes.

### Failure criteria

1. Any source is merged or cherry-picked as part of this PR.
2. A PromptPack-identity compensation is labeled for adoption.
3. Generated state or wholesale pack deletion is treated as implementation.
4. A later PR can claim this document as approval without its own exact
   allowlist and owner approval.
5. Any changed path in the audited ranges is left unclassified.

## 9. Risk Assessment

### Low-risk areas

- Recording immutable Git evidence and documentation-only dispositions.

### Medium-risk areas with mitigation

- Grouping many pack and probe files could hide exceptions. Mitigation: group
  only by identical operation and ownership; counts are recorded explicitly.
- Green historical tests could be mistaken for architectural approval.
  Mitigation: the guardrails state that test consistency and canon alignment
  are separate decisions.

### High-risk areas with mitigation

- Wholesale adoption would reintroduce pack-only compensation and destructive
  content changes. Mitigation: runtime files are forbidden and each future
  owner requires a separately approved spec.

### Rollback plan

Revert only the documentation change. No runtime, user data, or comparison
branch requires rollback.

## 10. Tech Debt Analysis

### Debt removed

- Ambiguity over whether the three later commits or branches should be merged.
- Unowned useful fixes hidden inside mixed-purpose commits.
- False equivalence between passing historical tests and current architectural
  validity.

### Debt intentionally deferred

| Debt | Owner |
|---|---|
| Conflicting pytest surfaces and tracked probe debris | `PR-MVP-010` |
| Reduced NJR and source-conditional identity | `PR-MVP-020` |
| Typed submission/acceptance and authoritative preview projection | `PR-MVP-030` |
| Transactional queue batch semantics | `PR-MVP-040` |
| Pack inventory and conflict-safe one-file migration | `PR-MVP-050` |
| Queue UI clearing, image cardinality, optional ADetailer decision, WebUI failure handling | `PR-MVP-060` |
| Typed native-SVD blank-prompt behavior | `PR-MVP-070` |
| Diagnostic collision handling and quarantine of non-MVP UI/features | `PR-MVP-080` |

## 11. Documentation Updates

- Preserve the approved disposition in the final
  `docs/CompletedPR/PR-MVP-005-Post-Baseline-Delta-Disposition.md` record.
- Update `docs/StableNew Roadmap v2.6.md`; it remains the single active roadmap.
- Update `docs/DOCS_INDEX_v2.6.md`; it remains authoritative.
- No architecture, lifecycle, builder, DebugHub, or coding/testing canon changes
  because no runtime contract changes.
- The approved backlog copy is replaced by this single final CompletedPR record;
  roadmap/index locations are updated in the same change.

## 12. Dependencies

### Internal module dependencies

- Completed `PR-ARCH-MVP-001` canon amendment.
- Completed `PR-MVP-000` recovery baseline and repository completeness.
- Immutable Git objects for the four full commit IDs recorded in section 2.

### External tools or runtimes

- Git for immutable diff and worktree evidence.
- Python/pytest only for the already-recorded focused historical checks.
- No network, GPU, WebUI, or Hugging Face dependency.

## 13. Approval & Execution

Planner: Codex
Executor: Codex (documentation-only execution)
Reviewer: Rob
Approval Status: Implemented

Approval is evidenced by the owner's explicit 2026-09-05 instruction to
generate and approve `PR-MVP-005`. Approval covers only the allowed
documentation files and the dispositions in this record. It does not approve
runtime implementation or bulk branch integration.

## 14. Next Steps

1. Generate and approve `PR-MVP-010` with an exact allowlist for test collection,
   isolation, the 30 tracked probe-artifact removals, and configuration cleanup.
2. Carry each `ADOPT` or `REWRITE` item only in its named later PR after a fresh
   diff against the then-current recovery branch.

## Post-Implementation Summary and Closeout

Delivered:

- audited all 115 changed-file occurrences across the three linear delta ranges;
- approved 17 binding logical dispositions with named roadmap owners;
- recorded focused historical test evidence without integrating branch code;
- preserved every comparison branch and rejected wholesale merge/cherry-pick.

Actual files changed:

- `docs/CompletedPR/PR-MVP-005-Post-Baseline-Delta-Disposition.md`;
- `docs/StableNew Roadmap v2.6.md`;
- `docs/DOCS_INDEX_v2.6.md`.

Verification:

- `git diff --check` passed for every audited historical range and the final
  documentation change;
- repository completeness passed with 435 tracked Python source files;
- only the three allowed documentation files changed;
- `recovery/mvp-baseline`, `QOL-Work`, and `main` did not move during the audit.

Deferred debt and owners remain exactly as listed in section 10. The immediate
next PR is `PR-MVP-010`.
