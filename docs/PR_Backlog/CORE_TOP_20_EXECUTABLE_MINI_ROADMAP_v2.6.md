# CORE Top 20 Executable Mini-Roadmap v2.6

Status: Active backlog triage
Updated: 2026-03-29
Applies to: the split `PR-CORE-001` through `PR-CORE-020` proposal set in `docs/PR_Backlog/`

## 1. Purpose

This file is the active entry point for the split CORE proposal specs now stored
as individual `docs/PR_Backlog/PR-CORE-*.md` files.

The individual specs preserve the proposal detail. This mini-roadmap is the
repo-truth status and prioritization guide.

## 2. Repo-Truth Validation Summary

- `svd_native` already exists across controller, pipeline, runner, and GUI
  surfaces, and dedicated controller-to-runner coverage now exists in
  `tests/video/test_svd_integration.py`.
- the existing golden-path suite already covered core execution and
  AnimateDiff, and explicit SVD/workflow-video coverage now exists in
  `tests/integration/test_video_golden_paths_v26.py`.
- story-planning foundation already exists in `src/video/story_plan_models.py`,
  `src/video/story_plan_store.py`, and `src/video/story_plan_compiler.py`, and
  shipped as `PR-VIDEO-219`.
- stitching and interpolation foundation already exists through `PR-VIDEO-217`
  and the current SVD postprocess path.
- structured logging already exists through `PR-OBS-249A` through
  `PR-OBS-249D`.
- metadata logging and schema closure already exists through `PR-LEARN-261`
  through `PR-LEARN-264`.
- major GUI polish and consistency work already landed through `PR-GUI-220`,
  `PR-UX-265` through `PR-UX-279`, and `PR-GUI-283` through
  `PR-HARDEN-287`.
- a prompt-template catalog now exists in `data/prompt_templates.json`, backed
  by `src/utils/prompt_templates.py`, PromptPack JSON/TXT rendering support,
  and template-aware prompt authoring controls in the Prompt tab.
- a canonical `train_lora` path now exists through
  `src/pipeline/config_contract_v26.py`, `src/pipeline/stage_models.py`,
  `src/pipeline/stage_sequencer.py`, `src/pipeline/job_builder_v2.py`,
  `src/pipeline/pipeline_runner.py`, `src/training/character_embedder.py`,
  `src/training/lora_manager.py`, and the Character Training GUI tab.
- `pytest --collect-only -q` currently succeeds with `2964 tests collected`.
- no `src/video/frame_interpolator.py` or `src/tools/book_ingester.py` exists
  yet.

## 3. Status By PR

- `PR-CORE-001`: Completed 2026-03-29. The SVD runtime/controller/GUI/NJR
  substrate was already shipped; this PR closed the remaining config-contract
  validation, dedicated integration coverage, and canonical docs/bookkeeping.
- `PR-CORE-002`: Completed 2026-03-29. StableNew now ships a queue-backed
  `train_lora` stage, a thin external trainer subprocess wrapper, LoRA manifest
  registration, and a dedicated Character Training tab without introducing an
  alternate execution path.
- `PR-CORE-003`: Re-scope before execution. Story-planning foundations already
  shipped via `PR-VIDEO-219`; the remaining work is productization and import
  UX rather than basic models and storage.
- `PR-CORE-004`: Completed 2026-03-29. PromptPack authoring now has a shipped
  cinematic template catalog, template-aware pack serialization/export, and a
  thin GUI selector/preview surface without changing the NJR execution path.
- `PR-CORE-005`: Active, but merge or re-scope it together with
  `PR-CORE-017` to avoid duplicate ControlNet work.
- `PR-CORE-006`: Re-scope. Interpolation exists today; the remaining work is
  shared-module extraction or cross-backend reuse, not a net-new capability.
- `PR-CORE-007`: Largely absorbed by `PR-VIDEO-217`; only additional
  composition UX or export policies should be re-specified.
- `PR-CORE-008`: Active follow-on now that the character training and manifest
  registration path exists.
- `PR-CORE-009`: Re-scope. Sampler and scheduler controls already exist on the
  base-generation path; only missing video-specific scope should be newly
  specified.
- `PR-CORE-010`: Defer and re-measure. Recent hardening already landed major
  workload-aware runtime protection; future work should be benchmark-driven.
- `PR-CORE-011`: Completed 2026-03-29. The repo already had broad golden-path
  infrastructure; this PR closed the missing native SVD and workflow-video
  integration coverage in the active video path.
- `PR-CORE-012`: Largely absorbed by `PR-OBS-249A` through `PR-OBS-249D`; only
  additional metrics work should be re-specified.
- `PR-CORE-013`: Re-scope. Canonical config unification and shared app
  bootstrap already landed; only missing CLI or operator seams should remain.
- `PR-CORE-014`: Completed 2026-03-31. Multi-character support landed: actors
  survive `intent_config` round-trips, `resolve_actors_safe` skips missing
  characters with warnings, LoRA ordering convention (primary → secondary →
  style) is enforced through the existing `resolution_layer`, and a
  `MultiCharacterSelectorWidget` is available for GUI embedding.
- `PR-CORE-015`: Largely absorbed by `PR-LEARN-261` through `PR-LEARN-264`.
- `PR-CORE-016`: Largely absorbed by the completed GUI, UX, responsiveness, and
  consistency tranches.
- `PR-CORE-017`: Merge with `PR-CORE-005` unless maintainers want a separate
  deeper conditioning tranche.
- `PR-CORE-018`: Active, but sequence it after the next real core feature
  deliveries so the docs describe shipped behavior.
- `PR-CORE-019`: Active later. It depends on the re-scoped story-planning and
  productization path.
- `PR-CORE-020`: Keep as low-priority exploratory work.

## 4. Recommended Execution Order

1. `PR-CORE-014 - Multi-Character Support`  ✅ Completed 2026-03-31
  Reason: the character asset pipeline now exists, so the next highest-value
  follow-on is multi-character orchestration and prompt-side authoring.
2. merged `PR-CORE-005` / `PR-CORE-017` camera-control and ControlNet tranche
   Reason: avoid duplicating depth, pose, and camera-conditioning work across
   two overlapping specs.
3. `PR-CORE-008 - Style Consistency LoRA`
  Reason: style-control work is valuable, and it is now cleaner once the
  character training and manifest surfaces are established.
4. `PR-CORE-018 - Documentation and Usage Examples`
   Reason: this should explain shipped behavior, not lead it.
5. `PR-CORE-019 - Book Ingestion Tool`
   Reason: it depends on story-planning productization and documentation
   clarity.
6. `PR-CORE-020 - Research Spike: 3D and NeRF Exploration`
  Reason: it is strategically useful, but intentionally not a near-term
  delivery blocker.

## 5. Not Queue-Ready As Written

Do not execute these specs verbatim without re-scoping them against current
repo truth:

- `PR-CORE-003`
- `PR-CORE-006`
- `PR-CORE-007`
- `PR-CORE-009`
- `PR-CORE-010`
- `PR-CORE-012`
- `PR-CORE-013`
- `PR-CORE-015`
- `PR-CORE-016`

Use this file plus the canonical roadmap as the current source of truth for CORE
ordering. The split PR files preserve proposal detail and should only be
promoted into active execution when this mini-roadmap marks them ready, active,
or explicitly re-scoped.
