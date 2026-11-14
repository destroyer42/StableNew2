# P4-2 — Unified NJR compiler migration

Status: **AUTHORIZED 2026-11-13 (owner decisions, delegated to the coordinating session): P4-2A to P4-2F, run strictly in order A, B, C, D, E, F, each in a fresh session; P4-2E starts only after the coordinating session has reviewed the A-D results (OD-11). OD-8: the held Character Training compiler is included in P4-2B as a constructor swap only. OD-2 (new `SourceKind`), OD-3 (refusal-timing changes) and OD-4 (canonical configuration shape) are not adopted.** Produced by the design package recorded in
[the 2026-11-12 Focused assessment](../assessments/2026-11-12_p4_2_unified_njr_compiler_design.md), at `origin/main`
`67e0e559d1998321d567e78f9b4e16cf4e6d9807`. Date: 2026-11-12.

This file holds six bounded package contracts that follow `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`. Each package starts in
a fresh session, verifies its own start state against current `origin/main`, and needs its own owner authorization.
Do not repeat the architecture discovery; section and finding numbers (S1-S7, V1-V5, X1-X17, OD-1 to OD-11) refer to
the assessment.

## Target and shared rules

Target: `src/pipeline/njr_compiler.py` is the only module outside the read path (`NormalizedJobRecord.from_dict`,
`migrate_legacy_njr`) that constructs a `NormalizedJobRecord` or assigns a new `job_id` to one. Source planners keep
cardinality and source-specific preparation. The NJR schema, serialization, queue, runner and admission boundary do
not change.

Rules for every package:

1. No behavior change. `record.to_dict()` for every golden is byte-identical before and after; refusal type, message
   and point of refusal are identical; expansion order, counts and seeds are identical.
2. `STABLENEW_UPDATE_GOLDEN=1` is used only in P4-2A, on unchanged `main`. A later package that would need to change a
   golden file stops and reports instead.
3. The core calls only neutral seams (`apply_model_compile_policy`, `validate_profile_njr`, `require_njr_operation`,
   `require_no_retired_execution`). No model-family name appears in `njr_compiler.py`.
4. The core takes no service, registry handle or configuration manager.
5. Each package deletes the constructor code it replaces. There is no long-lived dual path; the transitional state
   ends at P4-2F.
6. Excluded everywhere: a new `SourceKind` (OD-2), any refusal-timing change (OD-3), a canonical configuration shape
   (OD-4), typed stage settings (P4-4), family-branch removal or executor moves (P4-5), Learning controller
   decomposition (P4-3), runtime composition (P3-2), the Model Comparison snapshot storage change (`STATUS.md`
   decision 9), and corrections of X1, X4, X5, X6, X7.
7. No package starts the application, a backend, a GPU probe or a physical qualification run.

Dependency order: **A -> B -> C -> D -> E -> F**. D needs C because a non-txt2img Learning variant is built by
`ReprocessJobBuilder`. E needs only B technically; it is placed after D so the core is proven on every other route
first (OD-11). F needs C, D and E.

Common template fields, identical for all six unless a package states otherwise:

- Execution location: Local (golden tests and the PR gate need a checkout; no GPU or runtime).
- Preferred host: none; stay in whichever fresh session starts the package.
- Worktree: a new worktree and short-lived branch from current `origin/main`; the owner's `main` checkout is not used.
- Controller Surface Assessment: no ratcheted controller gains lines. Where a controller file is touched, its line
  count must not rise and its ceiling is lowered if it shrinks.
- Review/Repair Budget: one batched repair and reverification cycle for confirmed in-scope findings.
- Token-Efficient Validation Plan: (1) `pytest tests/golden` and the touched route's subsystem tests; (2) reuse
  accepted evidence for untouched routes; (3) `python tools/ci/run_pr_gate.py` once, late; (4) inspect the final diff
  and run `git diff --check`.
- Physical/External Evidence Freeze: not applicable.
- Stop conditions: a golden or refusal baseline would have to change; a production behavior change becomes necessary;
  an NJR schema or persisted-data change becomes necessary; scope reaches an excluded item; a higher execution class
  is discovered.
- Completion report: per `AGENTS.md` section 8, with the `Model / usage` line measured by `tools/usage_report.py`.

---

## P4-2A — Baseline characterization

### Objective

- Outcome: every production-active compile and derivation route has a record golden, a refusal baseline and a
  canonical queue-admission check, generated on unchanged `main`.
- In scope: new tests and snapshot files under `tests/golden/`; reuse of `tests/helpers/njr_queue_harness.py` and of
  existing subsystem fixtures. New goldens: generic with config variants and with ADetailer; PromptPack with a 2x2
  Matrix, with the randomizer on, with one LoRA and one embedding, and with one exact profile; reprocess with img2img
  and with a frozen mask; Learning ordinary strict and legacy, one Model Comparison arm, one Two-Axis Grid cell, one
  Prompt x Model Matrix cell, one non-txt2img variant; history variation; replay of a PromptPack parent that belonged
  to a batch; sequence resume and replay; native SVD; Comfy Video Workflow; Movie Clips. One refusal table per route
  family recording exception type and message for: an exact profile's unsupported operation, an enabled retired
  stage, an empty txt2img prompt, a missing input image. One fake-backend admission test per route family.
- Explicit exclusions: any change under `src/`; a new test orchestration framework; changes to the six existing
  snapshot files.

### Execution class and model recommendation

- Execution class: Standard.
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High. Known architecture, many fixtures; the
  risk is completeness, not ambiguity.
- Expected usage: about 10M cache-read, 60k output.
- Separable hard part: none.

### Exact start state and authorities

- Required start SHA: current `origin/main`; record it. If any S1-S7 or V1-V5 file changed since `67e0e559`, re-read
  that file before writing its golden.
- Canonical docs: `docs/Subsystems/Testing/TESTING_AND_CI.md` section on `tests/golden/`; the assessment sections 2
  and 6.

### Surface assessment

- Files allowed to change: `tests/golden/**`; a helper under `tests/helpers/` only if two goldens need the same
  fixture.
- Controller or coordinator surface touched: No. Architecture authority changed: No.

### Acceptance and evidence reuse

- Required evidence: every route in assessment section 6.2 has the three kinds of test; injected ids make every
  snapshot deterministic (no masked random id in new files); the suite passes twice in a row and on the Windows lane;
  the "every golden is owned by a test" check covers the new files.
- A baseline that exposes a second-application difference in a profile policy (X2) is recorded as observed and
  reported; it is not fixed here.
- Completion evidence: implementation and demonstration only; no qualification claim.
- Existing harness to reuse: `tests/helpers/njr_queue_harness.py`, `tests/pipeline/test_prompt_pack_job_builder.py`
  fixtures, Learning and video subsystem fixtures.
- Known non-blocking debt: X1 and X4 are frozen in the snapshots as they are.

### Documentation impact

- `docs/Subsystems/Testing/TESTING_AND_CI.md`: extend the `tests/golden/` row to name the route families and the
  refusal baselines. `STATUS.md`, roadmap, architecture, `CODEX_MAP.md`, `AGENTS.md`: none.

### Risk and rollback

Risk: low. Rollback: revert the commit; no production effect.

---

## P4-2B — Assembly core and leaf routes

### Status (2026-11-13): implemented on `refactor/p4-2b-njr-assembly-core`

- `njr_compiler.py` provides `PolicyState`, `CompileCheck`, `NjrDraft`, `NjrDerivation`, `compile_njr`, `derive_njr`,
  plus `RawImagePlan`, `FrozenExpectation`, `history_lineage` and `mint_job_id`. `checks` is an ordered tuple (not a
  set), so a route's refusal order is kept exactly.
- Through the core: the CLI (S1, `EFFECTIVE`), Character Training (S5, `EFFECTIVE`, constructor swap only, OD-8), history
  replay and batch retry (V1), Regenerate with Changes (V2, declared checks `OPERATION`, `PROFILE_NJR`) and the sequence
  resume and replay (V4). V4 now passes its directive to `compile_replay_intent` as `ReplayIntent.run_directives`, so
  the record is no longer amended after derivation.
- Kept in the planners, so that nothing changes: the replay's retired-execution checks run on the parent before the new
  identity is minted (the error carries the parent's `job_id`), and the batch-membership archive stays in
  `compile_replay_intent`.
- No route uses `RAW` yet; it is unit-tested only. P4-2E decides whether `JobBuilderV2` uses `RAW` (with a
  `RawImagePlan`) or `EFFECTIVE`.
- Ownership ratchet: `tests/pipeline/test_njr_compiler.py` fails if a migrated file constructs a record or calls
  `replace(..., job_id=...)`, or if the core names a model family. P4-2F replaces it with the repository-wide guard.
- Direct constructors that remain: S2 `job_builder_v2.py` and S3 `prompt_pack_job_builder.py` (P4-2E); S4
  `reprocess_builder.py` (P4-2C); S6 `learning_njr.py`, S7 `ordinary_njr.py` and V5 `ordinary_njr.py:98` (P4-2D); V3
  `replay_engine.py:161` (P4-2F); R1 `migrate_legacy_njr` (read path) and T1 `tools/qualification/img_forge_100/run.py`
  (operator-only, a named exception in P4-2F).

### Objective

- Outcome: `src/pipeline/njr_compiler.py` provides `NjrDraft`, `PolicyState`, `CompileCheck`, `compile_njr` and
  `derive_njr`. The CLI builder, the training compiler (subject to OD-8) and the derivation routes
  (`compile_replay_intent`, `compile_history_variation`, `sequence_resume`) assemble through it.
- In scope: the new module and its unit tests; `cli_njr_builder.py`, `training_njr_compiler.py`,
  `replay_njr_compiler.py`, `history_variation_compiler.py`, `src/video/sequence_resume.py` changed only at their
  construction or re-identification statement. `ordinary_njr.py:98` (V5) and `replay_engine.py:161` (V3) are left for
  P4-2D and P4-2F.
- Explicit exclusions: `JobBuilderV2`, PromptPack, reprocess, Learning; any change to which policy or check a route
  runs; a common refusal type.

### Execution class and model recommendation

- Execution class: Architectural (it introduces the boundary the rest of the sequence depends on).
- Model recommendation: Claude Code Opus 5.5 High; Codex GPT-6 Astra High. The interface must hold for routes it does
  not yet serve.
- Expected usage: about 10M cache-read, 50k output.
- Separable hard part: none.

### Exact start state and authorities

- Prerequisite: P4-2A merged. Owner decision OD-8 (include or exclude training).
- Canonical docs: assessment section 5.2; `docs/ARCHITECTURE_v2.6.md` sections 6-7.

### Surface assessment

- Files allowed to change: `src/pipeline/njr_compiler.py` (new), the five files above, `tests/pipeline/` for core unit
  tests.
- Controller or coordinator surface touched: No. Architecture authority changed: No (a new module inside the existing
  compiler layer; no invariant changes).

### Acceptance and evidence reuse

- Tests written first: unit tests for the three policy states (a `RAW` draft runs each step once; an `EFFECTIVE` draft
  runs none; a `FROZEN` draft is not transformed and an altered value is refused); `derive_njr` lineage tests
  equivalent to the existing replay tests.
- Required evidence: all P4-2A goldens and refusal baselines unchanged; `git grep "NormalizedJobRecord("` no longer
  lists the migrated files; no `replace(..., job_id=...)` remains in the migrated derivation files.
- Reused evidence: Learning, PromptPack, reprocess and video suites at the accepted P4-2A SHA.

### Documentation impact

- `docs/CODEX_MAP.md`: add `src/pipeline/njr_compiler.py` to the "Job record (NJR) and compilers" row.
  `docs/ARCHITECTURE_v2.6.md`: none until P4-2F. `STATUS.md`: none.

### Risk and rollback

Risk: low to medium (five small, single-purpose call sites). Rollback: revert; no persisted data is affected.

---

## P4-2C — Reprocess and video

### Status (2026-11-13): implemented on `refactor/p4-2c-njr-reprocess-video`

- `ReprocessJobBuilder.build_reprocess_job` (S4) now assembles through `compile_njr` with `PolicyState.EFFECTIVE` and
  `checks=()`: the planner still prepares stages, metadata, the video/image split and the image workload's backend
  options exactly as before; only the `NormalizedJobRecord(...)` statement and the source-kind alias table moved. The
  table is `reprocess_source_kind(source, is_video=...)` in the core (a video stage wins, then the alias, else
  `REPROCESS`); no other core interface changed, so the five package-B routes are untouched.
- Every route that reaches the statement is covered without editing its module: Reprocess, Review, Photo Optimize,
  curation, masked edit, outpaint, native SVD, Comfy Video Workflow, sequences, Movie Clips and Learning non-txt2img
  variants. All goldens and refusal baselines pass unchanged; no baseline data file was touched and
  `STABLENEW_UPDATE_GOLDEN` was not set.
- Ownership ratchet: `tests/pipeline/test_njr_compiler.py` now also covers `reprocess_builder.py` (no construction, no
  `replace(..., job_id=...)`); it grew a table test for `reprocess_source_kind` and a test that the builder declares an
  `EFFECTIVE` draft with no checks.
- Direct constructors that remain: S2 `job_builder_v2.py` and S3 `prompt_pack_job_builder.py` (P4-2E); S6
  `learning_njr.py`, S7 `ordinary_njr.py` and V5 `ordinary_njr.py:98` (P4-2D); V3 `replay_engine.py:161` (P4-2F);
  `njr_core_v26.py:1276`, R1 `migrate_legacy_njr` (read path) and T1 `tools/qualification/img_forge_100/run.py`
  (operator-only), plus the `pipeline_controller.py` references the P4-2F guard will classify.

### Objective

- Outcome: `ReprocessJobBuilder.build_reprocess_job` assembles through the core. Reprocess, Review, Photo Optimize,
  curation, masked edit, outpaint, native SVD, Comfy Video Workflow, sequences, Movie Clips and Learning non-txt2img
  variants are covered without editing their modules.
- In scope: `src/pipeline/reprocess_builder.py` at its construction statement; the source-kind alias table moves into
  the core unchanged.
- Explicit exclusions: `reprocess_admission.py`, the edit services, every `src/video/` module, grouping and chunking
  logic, `DEFAULT_STAGE_VALUES`, adding any construction-time check (OD-3).

### Execution class and model recommendation

- Execution class: Standard.
- Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol High. One statement with the highest fan-in in
  the compiler layer.
- Expected usage: about 8M cache-read, 40k output.

### Exact start state and authorities

- Prerequisite: P4-2B merged.
- Canonical docs: `docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md`, `docs/Subsystems/Video/VIDEO_PIPELINE.md` sections
  on admission.

### Surface assessment

- Files allowed to change: `src/pipeline/reprocess_builder.py`, `src/pipeline/njr_compiler.py`, tests.
- Controller or coordinator surface touched: No. Architecture authority changed: No.

### Acceptance and evidence reuse

- Required evidence: reprocess, image-edit, Learning non-txt2img, SVD, Video Workflow, sequence and Movie Clips goldens
  and refusal baselines unchanged; the per-row reason text of a Review preview and of a video batch is unchanged; the
  draft declares `checks` equal to today's (none at construction for this builder).
- Existing harness: `njr_queue_harness`; reprocess, masked edit, outpaint, photo optimize and video subsystem tests.

### Documentation impact

- None beyond the code map regeneration if the repository's generator requires it.

### Risk and rollback

Risk: medium by reach, low by change size. Rollback: revert one commit.

---

## P4-2D — Learning

### Objective

- Outcome: `learning_njr.assemble_txt2img_njr` and `ordinary_njr._materialize_txt2img` build `FROZEN` drafts and
  assemble through the core; the re-identification at `ordinary_njr.py:98` uses `derive_njr`.
- In scope: the two construction statements, the one derivation, and the equality check that already follows S6.
- Explicit exclusions: `LearningController`, `learning_controller_services/*`, freeze-time planning in
  `model_comparison.py`, `two_axis_grid.py`, `prompt_model_matrix.py`; the legacy (non-strict) defaults (X13); the
  snapshot-storage change in `STATUS.md` decision 9 (OD-10); any P4-3 extraction.

### Execution class and model recommendation

- Execution class: Standard.
- Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol High. Preview and Run equality is the
  contract; a wrong step order would be silent.
- Expected usage: about 10M cache-read, 40k output.

### Exact start state and authorities

- Prerequisite: P4-2B and P4-2C merged.
- Canonical docs: `docs/Subsystems/Learning/LEARNING.md` sections on Run materialization and frozen snapshots.

### Surface assessment

- Files allowed to change: `src/learning/learning_njr.py`, `src/learning/ordinary_njr.py`,
  `src/pipeline/njr_compiler.py`, tests.
- Controller or coordinator surface touched: No (`learning_controller.py` is not edited). Architecture authority
  changed: No.

### Acceptance and evidence reuse

- Tests written first: a `FROZEN` draft whose config differs from its frozen arm is refused with today's message; a
  changed compile policy between freeze and Run does not alter the record.
- Required evidence: all Learning goldens and refusal baselines unchanged, strict and legacy; `compile_all` admission
  tests unchanged.

### Documentation impact

- `docs/Subsystems/Learning/LEARNING.md`: one sentence replacing the "construction sites" pointer with the core.

### Risk and rollback

Risk: medium. Rollback: revert; saved experiments are not rewritten.

---

## P4-2E — Generic and PromptPack

### Objective

- Outcome: each PromptPack job is compiled once and the model compile policy runs exactly once per record. The generic
  path builds `RAW` drafts; PromptPack builds `EFFECTIVE` drafts after its own preparation.
- In scope: `JobBuilderV2` is split into an expansion planner (config variants, randomizer, seed mode, batch runs,
  returning configurations with their indexes) and draft construction; `PromptPackNormalizedJobBuilder` consumes the
  planner's expansion directly and no longer rebuilds a discarded record.
- Explicit exclusions: Matrix planning, Klein LoRA review, ControlNet and OpenPose compilation, prompt adaptation and
  rendering, config resolution, the `SourceKind.CLI` label on generic jobs (X1), the swallowed exception (X6), the
  silent entry drop (X7), `STATUS.md` decision 4 (batch runs on the state-fallback path).

### Execution class and model recommendation

- Execution class: Architectural (the only package that changes control flow).
- Model recommendation: Claude Code Opus 5.5 XHigh; Codex GPT-6 Astra XHigh.
- Expected usage: about 20M cache-read, 80k output.
- Separable hard part: none worth delegating; the hard part is the whole package.

### Exact start state and authorities

- Prerequisite: P4-2B merged; owner decision OD-11 after reviewing P4-2A-D.
- Canonical docs: `docs/Subsystems/PromptPacks/PROMPTPACKS_AND_PROMPTING.md` (compile sequence and the "new
  compile-time behavior" rule), `docs/Subsystems/Image/MODEL_PROFILES.md`.

### Surface assessment

- Files allowed to change: `src/pipeline/job_builder_v2.py`, `src/pipeline/prompt_pack_job_builder.py`,
  `src/pipeline/njr_compiler.py`, tests.
- Controller or coordinator surface touched: No, unless `PipelineController` must pass a renamed collaborator; then
  its line count must not rise.
- Architecture authority changed: No.

### Acceptance and evidence reuse

- Tests written first: an assertion that each shared step is invoked once per PromptPack record; exact-profile
  PromptPack goldens from P4-2A must already exist.
- Required evidence: all generic and PromptPack goldens unchanged, including Matrix, randomizer, LoRA, embedding and
  exact-profile cases; job order, `variant_index`, `variant_total`, batch indexes and seeds unchanged; Preview and
  admission equivalence tests unchanged; the Klein review still completes before the first draft exists.
- Stop and report if a snapshot differs only because the second policy application used to change a value. That
  outcome turns X2 into a wrong-output defect and needs an owner decision on which result is correct.

### Documentation impact

- `docs/Subsystems/PromptPacks/PROMPTPACKS_AND_PROMPTING.md`: update step 6 of the compile sequence and the audit C2
  note. `docs/Subsystems/Image/IMAGE_PIPELINE.md`: the Intent row.

### Risk and rollback

Risk: high relative to the others. Rollback: revert one commit; nothing persisted changes.

---

## P4-2F — Guard and cleanup

### Objective

- Outcome: a new independent construction or derivation site fails CI, and the leftovers of the migration are gone.
- In scope: an architecture test that fails when `NormalizedJobRecord(` appears in `src/` outside
  `njr_core_v26.py` and `njr_compiler.py`, when a `replace` call on a record sets `job_id` outside the core, or when a
  model-family identifier appears in `njr_compiler.py`; migration of `replay_engine.py:161` (V3) to `derive_njr`;
  removal of `create_adetailer_fixup_jobs` and `build_reprocess_jobs_batched` only with a reachability proof across
  `src/`, `tests/` and `tools/`; canonical documentation.
- Explicit exclusions: `tools/qualification/img_forge_100/run.py` (operator-only; listed as an allowed exception in
  the guard); `JobExecutionController.replay` (X15) and the CLI's direct run (X14), both OD-9.

### Execution class and model recommendation

- Execution class: Standard.
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.
- Expected usage: about 6M cache-read, 30k output.

### Exact start state and authorities

- Prerequisite: P4-2C, P4-2D and P4-2E merged. If the owner ends the sequence after P4-2D (assessment H10), this
  package runs with `job_builder_v2.py` and `prompt_pack_job_builder.py` as named exceptions and records X2 as open.

### Surface assessment

- Files allowed to change: a test under `tests/architecture/` or the existing ratchet location, `replay_engine.py`,
  `reprocess_builder.py` (deletions only), documentation.
- Controller or coordinator surface touched: No. Architecture authority changed: Yes, documentation only:
  `docs/ARCHITECTURE_v2.6.md` gains a short statement of the single assembly boundary and the three policy states.

### Acceptance and evidence reuse

- Required evidence: the guard fails on a deliberately added construction site and passes without it; all goldens
  unchanged; deleted symbols have no reference.

### Documentation impact

- `STATUS.md`: edit the Known debt line that lists "NJR construction at several sites". `docs/ARCHITECTURE_v2.6.md`:
  as above. `docs/CODEX_MAP.md`: the compilers row. `docs/Subsystems/Testing/TESTING_AND_CI.md`: the guard.
  `AGENTS.md`: none.

### Risk and rollback

Risk: low. Rollback: revert.

---

## Optional, separately gated

- **GUI/manual `SourceKind`** (OD-2, audit decision 13): corrects X1. It adds an enum value to the NJR, changes the
  `job_builder_v2` golden on purpose, and needs a stated rule for reading such records in an older build. Not part of
  this sequence.
- **Refusal-timing alignment** (OD-3): with the core in place, moving a check is a one-line change to a source's
  declared `checks`, plus its refusal baseline. Each move is a product-visible change and needs its own decision.

## Summary

| Package | Class | Claude Code / Codex | Expected usage | Risk |
|---|---|---|---|---|
| P4-2A Baseline characterization | Standard | Sonnet 5.5 High / GPT-6.1 Sol High | ~10M cache-read, 60k output | Low |
| P4-2B Assembly core and leaf routes | Architectural | Opus 5.5 High / GPT-6 Astra High | ~10M cache-read, 50k output | Low-medium |
| P4-2C Reprocess and video | Standard | Sonnet 5.5 XHigh / GPT-6.1 Sol High | ~8M cache-read, 40k output | Medium |
| P4-2D Learning | Standard | Sonnet 5.5 XHigh / GPT-6.1 Sol High | ~10M cache-read, 40k output | Medium |
| P4-2E Generic and PromptPack | Architectural | Opus 5.5 XHigh / GPT-6 Astra XHigh | ~20M cache-read, 80k output | High |
| P4-2F Guard and cleanup | Standard | Sonnet 5.5 High / GPT-6.1 Sol High | ~6M cache-read, 30k output | Low |

Usage figures are planning magnitudes, not measurements.
