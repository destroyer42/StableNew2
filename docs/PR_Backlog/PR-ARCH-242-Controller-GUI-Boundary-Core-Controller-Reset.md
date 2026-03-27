# PR-ARCH-242 - Controller GUI Boundary Core Controller Reset

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Phase 7 - Structural and architectural cleanup queue
Date: 2026-03-26

## 1. Context & Motivation

Current repo truth still contains an active controller -> GUI inversion in the
core path:

- `src/controller/pipeline_controller.py` subclasses
  `src.gui.controller.PipelineController`
- core runtime code still imports controller/runtime state from
  `src.gui.state`
- `src/controller/job_service.py` imports
  `src.gui.pipeline_panel_v2.format_queue_job_summary`

This contradicts the v2.6 ownership model in:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GUI_Ownership_Map_v2.6.md`
- `docs/PR_Backlog/TOP_20_VERDICTS_AND_POST_VIDEO241_QUEUE_v2.6.md`

This PR exists now because the remaining post-`PR-VIDEO-241` queue explicitly
prioritizes the controller/core boundary reset first. Later items such as
`PR-CTRL-247`, `PR-APP-251`, and `PR-PORTS-248` become cleaner only after the
active controller -> GUI dependency is removed.

## 2. Goals & Non-Goals

### Goals

1. Remove the active controller -> GUI inheritance seam from
   `src/controller/pipeline_controller.py`.
2. Move shared controller/runtime state primitives out of `src.gui` into a
   controller-owned or otherwise non-GUI-owned module.
3. Remove core-path controller imports of GUI-only helper functions such as the
   queue-summary formatter.
4. Keep the public `src.controller.pipeline_controller.PipelineController`
   entrypoint intact for the rest of the repo.
5. Preserve the canonical execution path:
   `Intent -> Builder -> NJR -> JobService -> PipelineRunner`.
6. Add or update enforcement tests proving core controller/runtime modules no
   longer import from `src.gui`.

### Non-Goals

1. Do not shrink `PipelineController` into services in this PR; that belongs to
   `PR-CTRL-247`.
2. Do not archive, relocate, or fence historical modules in this PR; that
   belongs to `PR-ARCH-243`.
3. Do not change queue, runner, NJR, backend, or artifact contracts.
4. Do not redesign GUI state ownership beyond moving shared runtime/controller
   primitives out of `src.gui`.
5. Do not use compatibility execution shims or create a second controller path.

## 3. Guardrails

- `NormalizedJobRecord` remains the only outer job contract.
- Fresh execution remains queue-only.
- `PipelineRunner.run_njr(...)` remains the only production runner entrypoint.
- This PR may touch controller/core and GUI import boundaries, but it may not
  introduce a new execution path, revive `DIRECT`, or change runner/backend
  semantics.
- The GUI may depend on controller-owned/runtime-owned primitives; the
  controller/core path may not depend on `src.gui` ownership modules.

## 4. Allowed Files

### Files to Create

- `src/controller/runtime_state.py`
- `src/controller/core_pipeline_controller.py`
- `tests/safety/test_controller_core_no_gui_imports.py`

### Files to Modify

- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/gui/controller.py`
- `src/gui/state.py`
- `src/gui/pipeline_panel_v2.py`
- active runtime files that currently import `src.gui.state`:
  - `src/pipeline/executor.py`
  - `src/pipeline/pipeline_runner.py`
  - active `src/gui/` files that import shared runtime/controller state
- active tests that currently import `src.gui.state` or `src.gui.controller`
- `docs/StableNew Roadmap v2.6.md` only if the runtime truth statement changes
  materially

### Forbidden Files

- `src/queue/*`
- `src/video/*`
- `src/pipeline/pipeline_runner.py` execution semantics beyond import-path
  relocation
- `src/pipeline/job_models_v2.py`
- `src/history/*`
- `src/learning/*`
- archive relocation targets under `docs/archive/` or `src/**/archive/**`
  except import updates that are strictly required to keep tests passing

## 5. Implementation Plan

### Step 1 - Introduce controller-owned runtime state

Create a new non-GUI-owned module for:

- `GUIState`
- `CancellationError`
- `CancelToken`
- `StateManager`
- `PipelineState`
- related small runtime-state helpers currently living in `src.gui.state`

Files:

- `src/controller/runtime_state.py`
- `src/gui/state.py`
- active import sites in `src/controller/`, `src/pipeline/`, and active
  `src/gui/` modules

Why:

- shared runtime/controller primitives must not be owned by `src.gui`

Tests:

- update active tests importing `src.gui.state`
- add/import safety coverage

### Step 2 - Extract a core controller base

Create a controller-owned base class containing the lifecycle/progress/cancel
logic currently living in `src.gui.controller.PipelineController`.

Files:

- `src/controller/core_pipeline_controller.py`
- `src/controller/pipeline_controller.py`
- `src/gui/controller.py`

Why:

- the core controller path must no longer subclass a GUI-owned class

Expected end state:

- `src/controller.pipeline_controller.PipelineController` derives from a
  controller-owned base
- `src.gui.controller` becomes GUI-edge only, or is reduced to a non-core
  compatibility surface with no reverse dependency from `src/controller`

Tests:

- update controller lifecycle/queue tests
- add safety test proving `src/controller/pipeline_controller.py` does not
  import `src.gui`

### Step 3 - Remove core-path GUI helper imports

Move the queue-summary formatter out of `src.gui.pipeline_panel_v2` into a
controller-owned or neutral helper module.

Files:

- `src/controller/job_service.py`
- `src/gui/pipeline_panel_v2.py`
- helper location chosen in this PR

Why:

- `JobService` is core orchestration and may not import a GUI panel module

Tests:

- update queue summary / queue panel / job service tests as needed

### Step 4 - Tighten safety coverage

Add explicit architecture-enforcement coverage for the new boundary.

Files:

- `tests/safety/test_controller_core_no_gui_imports.py`
- existing safety tests if they should be extended instead of duplicated

Why:

- the boundary should be mechanically enforced after this PR

Tests:

- focused safety and controller contract runs

### Step 5 - Validate no canonical-path regression

Run the core controller/queue/runner path tests and any targeted GUI contract
tests affected by the import relocation.

Files:

- tests only

Why:

- this PR changes ownership boundaries, so regression validation must prove the
  canonical path still holds

## 6. Testing Plan

### Unit tests

- `pytest tests/safety/test_controller_core_no_gui_imports.py -q`
- `pytest tests/test_cancel_token.py tests/gui/test_state_manager_legacy.py -q`
- `pytest tests/controller/test_controller_job_lifecycle.py tests/controller/test_pipeline_controller_queue_mode.py tests/controller/test_pipeline_controller_webui_gating.py -q`

### Integration tests

- `pytest tests/controller/test_core_run_path_v2.py tests/controller/test_preview_queue_history_flow_v2.py tests/controller/test_pipeline_preview_to_queue_v2.py -q`

### Journey or smoke coverage

- `pytest tests/pipeline/test_run_modes.py tests/pipeline/test_executor_cancellation.py tests/pipeline/test_pipeline_runner_cancel_token.py -q`

### Manual verification

1. Launch the app.
2. Preview and queue a small PromptPack job.
3. Confirm queue execution, stop/cancel behavior, and queue summaries still
   work.

## 7. Verification Criteria

### Success criteria

- `src/controller/pipeline_controller.py` no longer imports or subclasses
  `src.gui.controller.PipelineController`
- active core runtime/controller modules no longer import from `src.gui.state`
- `JobService` no longer imports from `src.gui.pipeline_panel_v2`
- canonical queue/runner tests remain green
- new safety coverage fails if a future core controller module imports `src.gui`

### Failure criteria

- any new compatibility execution seam is added
- `src.controller` still depends on GUI-owned controller/state modules in the
  active runtime path
- queue/runner behavior changes beyond ownership-boundary refactoring

## 8. Risk Assessment

### Low-risk areas

- queue-summary helper relocation
- safety-test additions

### Medium-risk areas with mitigation

- moving shared runtime-state primitives
  - mitigate by updating all active import sites in one PR and keeping focused
    cancellation/lifecycle tests green

### High-risk areas with mitigation

- changing the base class of `PipelineController`
  - mitigate by preserving the public controller API and running the full
    controller canonical-path suite before considering the PR complete

### Rollback plan

- restore the previous import/class structure in
  `src/controller/pipeline_controller.py`
- keep the controller-owned runtime-state module out of active imports until the
  refactor can be retried cleanly

## 9. Tech Debt Analysis

### Debt removed

- active controller -> GUI inheritance inversion
- core runtime ownership of shared state sitting under `src.gui`
- controller-layer dependency on GUI queue-summary formatting

### Debt intentionally deferred

- archive/reference relocation and final fencing
  - next PR: `PR-ARCH-243`
- deeper `PipelineController` service extraction
  - next PR: `PR-CTRL-247`
- broader architecture enforcement expansion
  - next PR: `PR-ARCH-246`

## 10. Documentation Updates

- add completion record under `docs/CompletedPR/` when implemented
- update `docs/StableNew Roadmap v2.6.md` only if it still describes the
  controller/GUI inversion as open after this PR lands
- update any active ownership doc if the new runtime-state module changes the
  canonical placement guidance

## 11. Dependencies

### Internal module dependencies

- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/pipeline/executor.py`
- `src/pipeline/pipeline_runner.py`
- active GUI files importing shared runtime state

### External tools or runtimes

- none beyond normal pytest/Tk availability for GUI-adjacent tests

## 12. Approval & Execution

Planner: Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## 13. Next Steps

1. Execute `PR-ARCH-242` after approval of this spec.
2. Follow with `PR-ARCH-243-Archive-Import-Fencing-and-Reference-Relocation`.
3. Then execute `PR-HYGIENE-244-Tracked-Runtime-State-Purge-and-Hygiene-Enforcement`.
