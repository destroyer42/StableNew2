# PR-POLISH-214-AAA-Stability-and-Performance-Pass

Status: Completed  
Completed: 2026-03-19

## Purpose

Finish the last convergence work in the original v2.6 unification plan and
leave the repo in a clean post-migration state before the next video/product
queue begins.

## What Landed

### 1. Final queue-only runtime cleanup

- removed `JobService.submit_direct()` from
  [src/controller/job_service.py](/c:/Users/rob/projects/StableNew/src/controller/job_service.py)
- removed the dead `run_njrs_direct()` helper from
  [src/controller/job_service.py](/c:/Users/rob/projects/StableNew/src/controller/job_service.py)
- updated active queue and compat tests so legacy direct-labeled jobs now prove
  queue-normalized behavior through `submit_job_with_run_mode(...)`, rather than
  keeping a separate compatibility API alive

### 2. Final GUI seam cleanup

- removed `is_direct_run_in_progress` from
  [src/gui/app_state_v2.py](/c:/Users/rob/projects/StableNew/src/gui/app_state_v2.py)
- deleted the obsolete `PipelineConfigPanel` shim module at
  [src/gui/panels_v2/pipeline_config_panel_v2.py](/c:/Users/rob/projects/StableNew/src/gui/panels_v2/pipeline_config_panel_v2.py)
- deleted shim-only legacy tests:
  [tests/test_adetailer_sync.py](/c:/Users/rob/projects/StableNew/tests/test_adetailer_sync.py)
  and
  [tests/gui_v2/test_adetailer_sync.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_adetailer_sync.py)
- removed the remaining shim-focused assertions from
  [tests/gui_v2/test_pipeline_layout_scroll_v2.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_pipeline_layout_scroll_v2.py)

### 3. Better canonical config mirroring in GUI state

- `AppStateV2.set_run_config(...)` now derives and stores:
  - `intent_config`
  - `execution_config`
  - `backend_options`
- the legacy `run_config` dict still exists as a GUI-facing projection, but it is
  no longer the only state shape retained by the app state container

## Verification

Focused suites passed:

- `pytest tests/pipeline/test_run_modes.py tests/queue/test_job_service_pipeline_integration_v2.py tests/gui_v2/test_run_controls_states.py tests/gui_v2/test_pipeline_layout_scroll_v2.py tests/compat/test_end_to_end_legacy_submission_modes.py tests/system/test_architecture_enforcement_v2.py -q`

Focused result:

- `72 passed, 12 skipped`

Collection baseline after the cleanup:

- `pytest --collect-only -q -rs` -> `2377 collected / 0 skipped`

Compile/import sanity passed for the touched runtime and test modules.

## Architectural Effect

This PR completes the original `PR-UNIFY-201` through `PR-POLISH-214`
unification sequence.

After this PR:

- there is no live `submit_direct()` runtime path
- there is no live `PipelineConfigPanel` shim path
- there is no direct-only GUI run-state flag
- the remaining work shifts from migration closure to productization:
  long-form video, stitch/continuity/planning layers, UX polish, and further
  controller/config cleanup

## Follow-On Work

The next queue now lives in:

- [StableNew Roadmap v2.6.md](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md)
- [StableNew_ComfyAware_Backlog_v2.6.md](/c:/Users/rob/projects/StableNew/docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md)

Immediate post-unification priorities:

- `PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence`
- `PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning`
- `PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification`
- `PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter`
