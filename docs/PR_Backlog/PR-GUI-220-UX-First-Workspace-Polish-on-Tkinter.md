# PR-GUI-220 - UX-First Workspace Polish on Tkinter

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Post-Unification UX Polish
Date: 2026-03-19

## Context & Motivation

### Problem Statement

StableNew now has the right architecture, but the workspace still feels like
multiple adjacent tools more than one coherent product. PromptPack, Queue,
History, SVD, Video Workflow, and Movie Clips all exist, but the user
experience is still thinner than the runtime underneath it.

### Why This Matters

The current recommendation is to stay on Tkinter for now. That means the next
quality gain should come from UX, not a toolkit rewrite. This PR is the first
deliberate pass on product flow, clarity, defaults, and cross-surface movement.

### Current Architecture

StableNew already has:

- queue-only submission
- canonical history/artifacts/replay
- SVD and Video Workflow surfaces
- Movie Clips surface

Missing product quality:

- tighter cross-surface handoff
- clearer status/result visibility
- more deliberate progressive disclosure
- less friction in the common image-to-video and history-to-video paths

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPR/PR-GUI-213-GUI-Queue-Only-and-Video-Surface-Cleanup.md`

## Goals & Non-Goals

### Goals

1. Improve UX on the existing Tkinter stack without replacing the toolkit.
2. Make Queue, History, SVD, Video Workflow, and Movie Clips feel like one
   workspace.
3. Improve progressive disclosure, empty states, handoff affordances, defaults,
   and result/status clarity.
4. Reduce modal friction in common flows: PromptPack to Queue, History to SVD,
   History to Video Workflow, sequence or video output to Movie Clips.

### Non-Goals

1. Do not replace Tkinter.
2. Do not perform another broad architectural refactor in this PR.
3. Do not add major new backend/runtime capabilities in this PR.
4. Do not create a heavy custom docking or timeline framework in this PR.

## Guardrails

1. UX polish must sit on top of the stable queue/NJR architecture.
2. Do not reintroduce legacy config panels or alternate submission flows.
3. Prefer small dedicated presenter/view-contract helpers over more controller
   sprawl.
4. Keep UI state and controller contracts aligned with canonical config layers.

## Allowed Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/gui/view_contracts/video_workspace_contract.py` | Shared UX contract for handoff, labels, and result summaries across video surfaces |
| `src/gui/controllers/video_workspace_handoff.py` | Lightweight handoff helper for cross-surface routing |
| `tests/gui_v2/test_video_workspace_handoff.py` | UX/handoff contract tests |

### Files to Modify

| File | Reason |
|------|--------|
| `src/gui/main_window_v2.py` | workspace-level navigation and visible status improvements |
| `src/gui/job_history_panel_v2.py` | clearer actions, empty states, and result affordances |
| `src/gui/views/video_workflow_tab_frame_v2.py` | better defaults and progressive disclosure |
| `src/gui/views/movie_clips_tab_frame_v2.py` | better source intake, result feedback, and status clarity |
| `src/gui/panels_v2/history_panel_v2.py` | history framing/status polish if still used |
| `src/gui/app_state_v2.py` | minimal UI-state support for improved workspace flow |
| `src/controller/video_workflow_controller.py` | support cleaner handoff/status communication |
| `src/controller/app_controller.py` | minimal glue only where the window or history needs it |
| `tests/gui_v2/test_job_history_panel_v2.py` | updated UX assertions |
| `tests/gui_v2/test_video_workflow_tab_frame_v2.py` | improved workflow UX assertions |
| `tests/gui_v2/test_movie_clips_tab_v2.py` | improved clip-surface UX assertions |
| `tests/gui_v2/test_main_window_persistence_regressions.py` | workspace-state assertions |

### Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/controller/job_service.py` | No runtime semantic changes |
| `src/pipeline/pipeline_runner.py` | This is a UX PR, not runner work |
| `src/video/comfy_*` | No backend changes here |
| `src/controller/archive/` | No legacy surfaces |

## Implementation Plan

### Step 1: Define shared workspace UX contracts

Add a lightweight shared contract for:

- handoff labels and source bundles
- result summaries
- empty-state copy and CTA rules
- surface capability labels

Files:

- create `src/gui/view_contracts/video_workspace_contract.py`
- create `src/gui/controllers/video_workspace_handoff.py`

### Step 2: Improve history and handoff UX

Make History a clearer launch point into video actions with better affordances,
labels, and disabled states.

Files:

- modify `src/gui/job_history_panel_v2.py`
- modify `tests/gui_v2/test_job_history_panel_v2.py`

### Step 3: Improve Video Workflow and Movie Clips flow

Add better defaults, status text, source summaries, and progressive disclosure.

Files:

- modify `src/gui/views/video_workflow_tab_frame_v2.py`
- modify `src/gui/views/movie_clips_tab_frame_v2.py`
- modify related tests

### Step 4: Improve top-level workspace clarity

Refine the main window and app state only enough to support smoother
cross-surface movement and persistence.

Files:

- modify `src/gui/main_window_v2.py`
- modify `src/gui/app_state_v2.py`
- modify `src/controller/video_workflow_controller.py`
- modify `src/controller/app_controller.py` only where necessary

## Testing Plan

### Unit Tests

- `tests/gui_v2/test_video_workspace_handoff.py`

### Integration Tests

- `tests/gui_v2/test_job_history_panel_v2.py`
- `tests/gui_v2/test_video_workflow_tab_frame_v2.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`
- `tests/gui_v2/test_main_window_persistence_regressions.py`

### Manual Testing

1. From History, hand off an image result into SVD and Video Workflow.
2. From a video result, verify appropriate actions route into Movie Clips or
   disable invalid actions.
3. Confirm better defaults and clearer status/result messaging across the video
   workspace.

## Verification Criteria

### Success Criteria

1. Cross-surface movement feels explicit and low-friction.
2. Video surfaces show clearer defaults, source summaries, and result states.
3. No architecture or runtime contracts are changed to achieve UX polish.

### Failure Criteria

1. UX polish depends on resurrecting legacy submission/state paths.
2. Backend or runner changes become necessary for basic UI improvements.
3. The GUI still feels like disconnected surfaces after the handoff and status
   pass.

## Risk Assessment

### Low-Risk Areas

- new view-contract and handoff helper files

### Medium-Risk Areas

- app-state and main-window persistence tweaks
  - Mitigation: keep changes additive and well-covered by GUI persistence tests

### High-Risk Areas

- accidental controller bloat
  - Mitigation: route reusable UX logic into small view-contract/helper modules

### Rollback Plan

Revert the workspace-handoff helper and surface-specific UI refinements while
keeping the underlying runtime intact.

## Tech Debt Analysis

### Tech Debt Removed

- disconnected UX across video-related surfaces
- ambiguous or thin handoff/status behavior

### Tech Debt Intentionally Deferred

- richer GUI config adapter work
  - Owner: `PR-CTRL-221`
- any future toolkit migration evaluation
  - Owner: future roadmap item after `PR-GUI-220`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `README.md` if surface descriptions materially change

## Dependencies

### Internal

- current GUI surfaces and controllers
- history/video workflow/movie clips contracts

### External

- none

## Approval & Execution

Planner: ChatGPT/Codex planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-GUI-220`.
2. Finish `PR-CTRL-221` to reduce remaining GUI/controller state debt.
3. Reassess toolkit needs only after this UX pass is complete.
