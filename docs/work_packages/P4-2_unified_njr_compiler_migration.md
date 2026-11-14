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

### Status (2026-11-13): implemented on `refactor/p4-2d-njr-learning`

- `learning_njr.assemble_txt2img_njr` (S6) now declares a `FROZEN` draft with `checks=(PROFILE_NJR,)` and a
  `FrozenExpectation` over `positive_prompt`, `negative_prompt` and `workload.backend_options` (the caller's own
  `mismatch_message` is the refusal text); `compile_njr` constructs the record, verifies the expectation, then runs the
  exact-profile check, in the order the function used before. It serves Model Comparison, Two-Axis Grid and the Prompt x
  Model Matrix.
- `ordinary_njr._materialize_txt2img` (S7) declares a `FROZEN` draft with no checks (it ran none) and a prompt
  expectation that cannot fail for values the caller passes; the strict Preview parity check still follows in
  `materialize_njr`. The non-txt2img re-identification (V5) is `derive_njr(record, NjrDerivation(job_id=...,
  provenance=...))` with no checks and the parent's source.
- Not changed: the legacy (non-strict) defaults (X13), each route's model-policy and configuration rules, the planners and
  Learning controllers. No core interface changed; no `RAW` or `EFFECTIVE` use was added. A malformed S6 configuration that
  lacks `prompt`, `negative_prompt` or `backend_options` now raises `KeyError` while the expectation is built instead of
  after construction (and a mismatch plus a missing later key reports the `KeyError`, not the mismatch): the code path
  for well-formed frozen arms is identical.
- Preview and Run: `tests/learning_v2/test_njr_preview_run_equality_p42d.py` compares the Preview compile with the Run
  compile (ordinary strict, Model Comparison, Prompt x Model Matrix) and pins that the compile policy is never run for a
  `FROZEN` draft. Apart from the minted `job_id`, the `output_plan` and the two `metadata` mappings, the records are equal.
- Ownership ratchet: `tests/pipeline/test_njr_compiler.py` now also covers `learning_njr.py` and `ordinary_njr.py`.
- Direct constructors that remain: S2 `job_builder_v2.py` and S3 `prompt_pack_job_builder.py` (P4-2E); V3
  `replay_engine.py:161` (P4-2F); `njr_core_v26.py:1276`, R1 `migrate_legacy_njr` (read path) and T1
  `tools/qualification/img_forge_100/run.py` (operator-only), plus the `pipeline_controller.py` references the P4-2F guard
  will classify. One more `replace(..., job_id=...)` sits outside the core: `src/learning/qualification_batch.py:400`
  compares a freshly compiled record with a stored one after giving it the stored identity; it produces no record and
  the P4-2F guard must classify it as a comparison.

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

### Status (2026-11-14): implemented on `refactor/p4-2e-njr-generic-promptpack`

- `JobBuilderV2` is split. `plan_expansion` returns one `ExpansionItem` per record (configuration, seed, variant and
  batch indexes, config variant, randomizer summary) for config variants, randomizer, seed mode and batch runs, in the
  old order. `build_jobs` (generic, S2) turns each item into a `RAW` draft with `checks=(PROFILE_NJR,)`; the core runs
  effective config, model policy, ADetailer (only without a `stages` key and with `pipeline.adetailer_enabled`),
  backend options and intent once per record. The identity is minted after the stage-conditional step, as before, so
  a refused draft consumes none. `SourceKind.CLI` (X1) is kept.
- `PromptPackNormalizedJobBuilder` (S3) consumes `plan_expansion` directly and builds one `EFFECTIVE` draft per record
  with `checks=(PROFILE_NJR,)`; the discarded intermediate `CLI` record, its second backend-option normalization and
  its second `validate_zimage_njr` are gone. Matrix planning, the Klein review (still complete before the first
  expansion), ControlNet/OpenPose, prompt adaptation and rendering and config resolution are unchanged.
- Core changes: `prepare_image_config` (steps 1-2, public so a planner can prepare the configuration its `EFFECTIVE`
  draft carries) and a reshaped `RawImagePlan` (`bind`, `adetailer_applies`, `stages_for(config, adetailer_mode)`,
  `mint_job_id`). No route but generic uses `RAW`; no service, registry or configuration manager was added.
- **Finding (X2 reclassified).** The two PromptPack policy applications aren't a redundant double call. Each one
  produces part of the record:
  - **Nested application** in `_prepare_entry`, once per prepared prompt. The stage chain, ADetailer, randomizer and
    batch inputs are built from its result, and its exact-profile refusals surface before the Klein review. Without
    it, a Klein pack's txt2img stage keeps the user's `DDIM`/24/7.5 instead of `Beta`/4/1.0 and fails backend admission.
  - **Flat application** on the payload, once per record. `_build_config_payload` drops the profile's
    `backend_options`, the `txt2img` section, `distilled_cfg_scale` and `sampler_name`, copies `vae: null` and carries
    the planner's `global_prompt_policy_source: legacy_runtime_fallback`. This application restores them (Z-Image:
    the profile's `txt2img` defaults section, `backend_options.model_profile`, `distilled_cfg_scale` 9.0,
    `sampler_name`, `vae: ""`, `frozen_njr`; Klein: `backend_options` and its `txt2img` section), and `workload.config`
    freezes its result; the exact-profile goldens pin these values.
- **Decision** (coordinating session under the owner's delegation, 2026-11-13): first (a), "one application, at the
  payload". It was withdrawn after the Klein evidence above. Then option 4: keep one application per configuration
  shape, with no output or policy-module change. **The plan's outcome "the model compile policy runs exactly once per
  record" is not achieved for PromptPack.** It is replaced by pinned counts (`tests/pipeline/test_njr_compile_invocations_p42e.py`):
  - generic: every shared step once per record;
  - PromptPack: per record, construction, exact-profile check, backend-option normalization, intent canonicalization
    and flat effective-config preparation once each; per prepared prompt, ADetailer once;
  - model policy: once per prepared prompt on the nested configuration plus once per record on the flat payload.
  Characterization tests pin what each application produces and that removing either changes the record.
- **Open design decision, after P4-2F, not implemented:** one policy result projected onto both shapes through a
  neutral projection seam in `src/image_backends/model_policy.py` (option 2). Rejected for E: profile rules copied into
  the planner (a second policy authority) and rebuilding the stage chain at draft time (moves stage construction
  relative to the Klein review).
- **Invocation counts, before → after.** Before is the instrumented `d46660fc`, 185 tests / 585 records; after is
  pinned by tests.

  | Step | Before (per PromptPack record) | After |
  |---|---|---|
  | Record constructions | 2 (S2 discarded + S3) | 1 |
  | `validate_zimage_njr` | 2 | 1 (`PROFILE_NJR`) |
  | Backend-option normalization | 2 | 1 |
  | Model policy | 1 per prepared prompt + 1 per record | unchanged, now explicit |
  | `prepare_effective_config` | 1 (S2) | 1 (`prepare_image_config`) |
  | ADetailer | 1 per prepared prompt | unchanged |
  | Intent canonicalization | 1 | unchanged |
- **Differential proof.** `to_dict()` (or refusal type and message) was captured for 86 inputs on unchanged
  `d46660fc` and again after the split: identical for all 86. The harness lives outside the repository; the inputs are
  covered in the repository by the goldens and the subsystem suites.
  - Generic: the golden inputs; config variants × batch runs; ADetailer on, off and with a `stages` key; Z-Image (plain,
    global positive composed and disabled, operator overrides of sampler/steps/CFG/VAE/CLIP skip/distilled CFG,
    seed `None`, profile without its checkpoint, bad geometry); Klein (plain, with ADetailer); SDXL nested model; a
    dataclass config; randomizer with choices and with fixed seed; seed modes FIXED, PER_VARIANT and NONE on the
    non-randomized path; output settings and pack usage; an unsupported config type. Every generic case was followed
    by a second build on the same builder, to show the id sequence after success and after refusal.
  - PromptPack, SDXL: plain; two entries; 2x2 Matrix; randomizer seeded and unseeded; Matrix × randomizer × batch; 3
    batch runs; LoRA, embeddings and negatives; hires on and off (the flattening keeps or drops the hires keys);
    refiner; operator values; ADetailer; frozen global positive; output dir and images per prompt; invalid loop type;
    `learning_` pack without pack config; enabled AnimateDiff refusal.
  - PromptPack, Z-Image: plain; adapted LoRA and embedding; negative; operator overrides; explicit profile values;
    global positive on; randomizer; ADetailer, upscale and hires refusals; bad geometry; loop-count refusal; weighted
    prose.
  - PromptPack, Klein: SDXL-style user defaults; Matrix; no LoRAs; operator overrides with 2 batch runs; ADetailer;
    batch selection `last` and `specific`; cancelled selection.
  - PromptPack, SDXL adaptation.
- All goldens, refusal tables, refusal order and Klein tests pass unchanged. No baseline data file changed and
  `STABLENEW_UPDATE_GOLDEN` was not set. Metadata is covered by the `to_dict()` equality: the flat application's
  `effective_configuration` evidence is discarded, as S2's was; `adetailer_mode` comes from the planner's single
  ADetailer compile; `global_prompt_policy_source` comes from the flat application.
- Tests that watched the old seam now watch the new one: the Klein "no draft before review" sentinels patch
  `plan_expansion` instead of `build_jobs`; the "one model compile policy" identity check and the backend-normalization
  producer check name `njr_compiler.py` for the generic route. The ownership ratchet covers `job_builder_v2.py` and
  `prompt_pack_job_builder.py`.
- Preserved although it looks wrong (excluded from E): X1 (generic `SourceKind.CLI`), X6 (the generic path swallows
  every compile exception, `pipeline_controller.py`), X7 (an unloadable pack entry is dropped with a log line),
  `STATUS.md` decision 4 (batch runs on the state-fallback path), the two policy applications above. Also the
  PromptPack randomizer plan: it has no choices, so `max_variants > 1` still yields one variant.
- Direct constructors that remain: V3 `replay_engine.py:161` (P4-2F); `njr_core_v26.py:1276` (`migrate_legacy_njr`, read
  path); T1 `tools/qualification/img_forge_100/run.py` (operator-only); the `pipeline_controller.py` references and the
  `replace(..., job_id=...)` comparisons in `replay_njr_compiler.py` and `learning/qualification_batch.py:400`, all for
  the P4-2F guard to classify.

#### Routes on the core (facts for the later harmonisation decision)

Shared steps: E effective-config preparation, P model compile policy, A ADetailer compile, B backend-option
normalization, I intent canonicalization. "Planner" means the route runs the step itself before handing over its draft.

| Route | Entry | `PolicyState` | `CompileCheck` tuple (in order) | Shared steps run | Not run |
|---|---|---|---|---|---|
| CLI (S1) | `cli_njr_builder.build_cli_njr` | `EFFECTIVE` | `()` | P, A, B, I (planner) | E |
| Generic Pipeline tab (S2) | `JobBuilderV2.build_jobs` | `RAW` | `(PROFILE_NJR,)` | E, P, A (conditional), B, I (core, once per record) | none |
| PromptPack (S3) | `PromptPackNormalizedJobBuilder.build_jobs` | `EFFECTIVE` | `(PROFILE_NJR,)` | P twice: nested per prepared prompt (planner) and flat per record (`prepare_image_config`); E per record (`prepare_image_config`; Z-Image also `normalize_profile_owned_values` per prepared prompt); A per prepared prompt; B and I per record (planner) | none |
| Reprocess family (S4: Reprocess, Review, Photo Optimize, curation, masked edit, outpaint, SVD, Video Workflow, sequences, Movie Clips, Learning non-txt2img) | `ReprocessJobBuilder.build_reprocess_job` | `EFFECTIVE` | `()` | B (planner) | E, P, A, I |
| Character Training (S5) | `training_njr_compiler` | `EFFECTIVE` | `()` | I (planner) | E, P, A, B |
| Learning frozen arm (S6: Model Comparison, Two-Axis Grid, Prompt x Model Matrix) | `learning_njr.assemble_txt2img_njr` | `FROZEN` (prompt, negative, backend options) | `(PROFILE_NJR,)` | none at Run (validated at freeze) | E, P, A, B, I |
| Learning ordinary txt2img (S7) | `ordinary_njr._materialize_txt2img` | `FROZEN` (prompt, negative) | `()` | B (planner) | E, P, A, I |
| Learning non-txt2img re-identification (V5) | `ordinary_njr` | derivation | `()` | none | all |
| History replay and batch retry (V1) | `compile_replay_intent` | derivation | `()` (retired checks run on the parent in the planner) | none | all |
| Sequence resume and replay (V4) | `sequence_resume` via `compile_replay_intent` | derivation | `()` | none | all |
| Regenerate with Changes (V2) | `history_variation_compiler` | derivation | `(OPERATION, PROFILE_NJR)` | none | all |

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
