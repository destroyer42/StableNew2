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
  surfaces, but there is still no dedicated `tests/video/test_svd_integration.py`
  coverage.
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
- `pytest --collect-only -q` currently succeeds with `2964 tests collected`.
- no `src/training/character_embedder.py`, `src/training/lora_manager.py`,
  `src/services/prompt_templates.py`, `data/prompt_templates.*`,
  `src/video/frame_interpolator.py`, or `src/tools/book_ingester.py` exists
  yet.

## 3. Status By PR

- `PR-CORE-001`: Ready now. Treat this as integration hardening for the
  already-shipped SVD substrate, not as a greenfield build.
- `PR-CORE-002`: Active after `PR-CORE-001`. The training and LoRA-management
  surface is still absent from the repo.
- `PR-CORE-003`: Re-scope before execution. Story-planning foundations already
  shipped via `PR-VIDEO-219`; the remaining work is productization and import
  UX rather than basic models and storage.
- `PR-CORE-004`: Active. No prompt-template loader or template library exists
  yet.
- `PR-CORE-005`: Active, but merge or re-scope it together with
  `PR-CORE-017` to avoid duplicate ControlNet work.
- `PR-CORE-006`: Re-scope. Interpolation exists today; the remaining work is
  shared-module extraction or cross-backend reuse, not a net-new capability.
- `PR-CORE-007`: Largely absorbed by `PR-VIDEO-217`; only additional
  composition UX or export policies should be re-specified.
- `PR-CORE-008`: Active follow-on once character and style asset management is
  clearer.
- `PR-CORE-009`: Re-scope. Sampler and scheduler controls already exist on the
  base-generation path; only missing video-specific scope should be newly
  specified.
- `PR-CORE-010`: Defer and re-measure. Recent hardening already landed major
  workload-aware runtime protection; future work should be benchmark-driven.
- `PR-CORE-011`: Active after `PR-CORE-001`, but re-scope it from collection
  recovery to end-to-end product journeys and SVD/video golden paths.
- `PR-CORE-012`: Largely absorbed by `PR-OBS-249A` through `PR-OBS-249D`; only
  additional metrics work should be re-specified.
- `PR-CORE-013`: Re-scope. Canonical config unification and shared app
  bootstrap already landed; only missing CLI or operator seams should remain.
- `PR-CORE-014`: Active follow-on after `PR-CORE-002`.
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

1. `PR-CORE-001 - Finalize Native SVD Integration`
   Reason: the runtime, controller, and GUI substrate already exists, making
   this the highest-leverage feature closure with the lowest architectural
   uncertainty.
2. `PR-CORE-011 - End-to-End Pipeline Tests`
   Reason: after `PR-CORE-001`, the highest remaining leverage is confident
   golden-path coverage for SVD/video and cross-surface orchestration.
3. `PR-CORE-004 - Cinematic Prompt Template Library`
   Reason: this fills a clear missing authoring layer without conflicting with
   shipped architecture.
4. `PR-CORE-002 - Character Embedding Pipeline`
   Reason: this is still missing and high value, but it is larger and more
   operationally heavy than the authoring-layer work above.
5. `PR-CORE-014 - Multi-Character Support`
   Reason: it should land only after a character asset pipeline exists.
6. merged `PR-CORE-005` / `PR-CORE-017` camera-control and ControlNet tranche
   Reason: avoid duplicating depth, pose, and camera-conditioning work across
   two overlapping specs.
7. `PR-CORE-008 - Style Consistency LoRA`
   Reason: style-control work is valuable, but it is cleaner once character and
   training surfaces are established.
8. `PR-CORE-018 - Documentation and Usage Examples`
   Reason: this should explain shipped behavior, not lead it.
9. `PR-CORE-019 - Book Ingestion Tool`
   Reason: it depends on story-planning productization and documentation
   clarity.
10. `PR-CORE-020 - Research Spike: 3D and NeRF Exploration`
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
