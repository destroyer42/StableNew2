# PR-CTRL-221 - GUI Config Adapter and Final Controller Shrink

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Post-Unification Controller and GUI Cleanup
Date: 2026-03-19

## Context & Motivation

### Problem Statement

The unification sequence removed the last live legacy submission seams, but the
GUI still carries a transitional compatibility projection in `AppStateV2.run_config`,
and `AppController` and `PipelineController` remain oversized. UX work should
not hard-code against that transitional shape.

### Why This Matters

This is the final cross-cutting cleanup needed to keep the now-stable GUI from
re-accumulating architectural debt. It also supports future video and planning
surfaces without forcing them to bind directly to a legacy-ish dict facade.

### Current Architecture

Current truth:

- canonical config layering exists
- `AppStateV2` mirrors canonical config layers
- `run_config` still exists as a GUI-facing dict projection
- top-level controllers are still larger than they should be

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPR/PR-CTRL-205-Controller-Decomposition-and-Port-Boundaries.md`
- `docs/CompletedPR/PR-CONFIG-206-Canonical-Config-Unification.md`
- `docs/CompletedPR/PR-POLISH-214-AAA-Stability-and-Performance-Pass.md`

## Goals & Non-Goals

### Goals

1. Introduce a dedicated GUI config adapter that exposes a stable GUI-facing API
   over canonical config layers.
2. Reduce direct `run_config` dict usage across GUI/controller surfaces.
3. Extract another small, well-bounded set of controller responsibilities from
   `AppController` and `PipelineController`.
4. Keep all fresh execution and runtime behavior unchanged.

### Non-Goals

1. Do not change queue semantics, NJR semantics, or runner behavior.
2. Do not perform a sweeping GUI rewrite.
3. Do not remove every last compatibility accessor in one unsafe pass.
4. Do not add new product features beyond the adapter and controller cleanup.

## Guardrails

1. The GUI config adapter is a facade over canonical layers, not a new config
   model.
2. Any remaining `run_config` projection must become clearly derived rather than
   primary.
3. Controller extraction must reduce top-level controller bulk, not move logic
   into another god-object.
4. No live archive or `PipelineConfig` semantics may return.

## Allowed Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/gui/config_adapter_v26.py` | Stable GUI-facing adapter over canonical config layers |
| `src/controller/app_controller_services/gui_config_service.py` | Small service for adapter construction and update flows |
| `src/controller/pipeline_controller_services/history_handoff_service.py` | Focused extraction for history or handoff-heavy controller logic |
| `tests/gui_v2/test_config_adapter_v26.py` | Adapter coverage |
| `tests/controller/test_gui_config_service.py` | Service coverage |
| `tests/controller/test_history_handoff_service.py` | Extraction coverage |

### Files to Modify

| File | Reason |
|------|--------|
| `src/gui/app_state_v2.py` | Integrate adapter and reduce direct dict reliance |
| `src/controller/app_controller.py` | Delegate more GUI-config responsibility |
| `src/controller/pipeline_controller.py` | Delegate another bounded concern |
| `src/controller/app_controller_services/run_submission_service.py` | Align with adapter where needed |
| `src/gui/views/video_workflow_tab_frame_v2.py` | Use adapter instead of raw dict access where relevant |
| `src/gui/views/movie_clips_tab_frame_v2.py` | Use adapter or shared config access if needed |
| `tests/controller/test_app_controller_*` | update affected controller tests |
| `tests/controller/test_pipeline_controller_*` | update affected extraction tests |
| `tests/gui_v2/test_video_workflow_tab_frame_v2.py` | adapter usage assertions |

### Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/pipeline_runner.py` | No runner changes |
| `src/controller/job_service.py` | No queue semantic changes |
| `src/controller/archive/` | No legacy runtime seams |
| `src/video/*` | No backend/runtime changes in this PR unless strictly required for typing imports only |

## Implementation Plan

### Step 1: Add GUI config adapter

Create a dedicated GUI adapter that exposes stable getters/setters and view-safe
projection methods over:

- intent config
- execution config
- backend options

Files:

- create `src/gui/config_adapter_v26.py`
- create `tests/gui_v2/test_config_adapter_v26.py`

### Step 2: Integrate adapter into app state

Make `AppStateV2` own the adapter or expose it as the primary config surface,
with `run_config` remaining only as a derived compatibility projection if still
needed.

Files:

- modify `src/gui/app_state_v2.py`

### Step 3: Extract controller services

Extract at least one more bounded responsibility from each oversized controller,
favoring GUI-config and history-handoff concerns.

Files:

- create `src/controller/app_controller_services/gui_config_service.py`
- create `src/controller/pipeline_controller_services/history_handoff_service.py`
- modify `src/controller/app_controller.py`
- modify `src/controller/pipeline_controller.py`

### Step 4: Convert affected GUI surfaces

Update video-oriented surfaces and any touched queue/history glue to consume the
adapter/service APIs instead of raw `run_config` dict handling.

Files:

- modify `src/gui/views/video_workflow_tab_frame_v2.py`
- modify `src/gui/views/movie_clips_tab_frame_v2.py`
- modify affected tests

## Testing Plan

### Unit Tests

- `tests/gui_v2/test_config_adapter_v26.py`
- `tests/controller/test_gui_config_service.py`
- `tests/controller/test_history_handoff_service.py`

### Integration Tests

- focused `tests/controller/test_app_controller_*`
- focused `tests/controller/test_pipeline_controller_*`
- `tests/gui_v2/test_video_workflow_tab_frame_v2.py`

### Manual Testing

1. Change GUI config on active surfaces and verify state remains synchronized.
2. Queue a run and confirm no runtime behavior changes.
3. Verify the GUI still restores persisted state correctly.

## Verification Criteria

### Success Criteria

1. GUI-facing config access uses a dedicated adapter instead of raw dict shape
   in the touched surfaces.
2. `AppController` and `PipelineController` shrink further by meaningful,
   bounded extractions.
3. Runtime behavior is unchanged.

### Failure Criteria

1. A new shadow config model is introduced.
2. Controllers shrink only by moving logic into an equally broad replacement
   object.
3. GUI state becomes less synchronized with canonical config layers.

## Risk Assessment

### Low-Risk Areas

- new adapter and service files

### Medium-Risk Areas

- `AppStateV2` projection changes
  - Mitigation: keep `run_config` derived until all touched surfaces are migrated

### High-Risk Areas

- controller extraction regressions
  - Mitigation: extract one bounded concern at a time and cover with focused tests

### Rollback Plan

Revert the adapter/service integration and restore prior direct state access
while keeping the canonical config-layer contract intact.

## Tech Debt Analysis

### Tech Debt Removed

- direct GUI reliance on transitional `run_config` dict shape
- remaining avoidable top-level controller bulk

### Tech Debt Intentionally Deferred

- any future toolkit migration or larger presentation-layer overhaul
  - Owner: future roadmap item after `PR-GUI-220`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md` only if residual debt status materially changes

## Dependencies

### Internal

- `AppStateV2`
- existing controller services
- GUI surfaces touched by `PR-GUI-220`

### External

- none

## Approval & Execution

Planner: ChatGPT/Codex planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-CTRL-221` after `PR-GUI-220` or in parallel only if file ownership stays disjoint.
2. Reassess remaining controller debt after this extraction.
