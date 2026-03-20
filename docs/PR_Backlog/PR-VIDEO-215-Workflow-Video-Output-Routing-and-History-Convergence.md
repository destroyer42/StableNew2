# PR-VIDEO-215 - Workflow-Video Output Routing and History Convergence

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Post-Unification Video Productization
Date: 2026-03-19

## Context & Motivation

### Problem Statement

`video_workflow` is now a real NJR-driven stage, but its output handling is
still thinner than the mature still-image path. Workflow-video outputs are
functional, but output routing, recent-result affordances, history summaries,
and handoff behavior are still more stage-specific than they should be.

### Why This Matters

StableNew now has a real short-form workflow-video path. If output routing and
history behavior stay inconsistent, the user experience will continue to feel
like a prototype even though the core architecture is stable.

### Current Architecture

Current runtime:

`Intent -> NJR -> JobService Queue -> PipelineRunner -> video backend -> canonical artifacts/history/replay`

Current gap:

- workflow-video artifacts are canonical but not yet as richly routed as image outputs
- history and recent-output surfaces still contain stronger assumptions for still-image than workflow-video
- Video Workflow, SVD, and Movie Clips are adjacent surfaces, not yet a clean handoff set

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`
- `docs/CompletedPR/PR-VIDEO-207-NJR-Video-Contract-Completion.md`
- `docs/CompletedPR/PR-GUI-213-GUI-Queue-Only-and-Video-Surface-Cleanup.md`
- `docs/CompletedPR/PR-OBS-212-Image-Video-Diagnostics-and-Replay-Unification.md`

## Goals & Non-Goals

### Goals

1. Make workflow-video output routing deterministic and explicit, including a
   canonical primary artifact, manifest paths, preview paths when available,
   and handoff-safe output bundles.
2. Make history and recent-result handling for workflow-video as coherent as
   still-image output handling.
3. Make handoff between Video Workflow, SVD, and Movie Clips explicit and
   generic instead of stage-name driven where possible.
4. Keep all routing and history behavior fully NJR-driven and artifact-driven.

### Non-Goals

1. Do not add long-form sequencing in this PR.
2. Do not add stitching, interpolation, or continuity features in this PR.
3. Do not redesign the whole GUI; only improve video-output convergence.
4. Do not introduce a second video history schema or a second artifact schema.

## Guardrails

1. NJR remains the only outer job contract.
2. `VideoExecutionRequest` and backend-local output details remain internal to
   `src/video/`.
3. No backend workflow JSON may leak into GUI/controller/public history
   contracts.
4. Do not revive stage-specific output handling where a generic video-artifact
   path can be used instead.
5. Do not touch queue semantics, migration tooling, or unrelated controller
   architecture.

## Allowed Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/video/video_artifact_helpers.py` | Normalize workflow-video output bundles, previews, and handoff metadata |
| `tests/video/test_video_artifact_helpers.py` | Unit coverage for generic video-artifact routing helpers |

### Files to Modify

| File | Reason |
|------|--------|
| `src/video/comfy_workflow_backend.py` | Emit richer workflow-video artifact details |
| `src/pipeline/pipeline_runner.py` | Preserve generic video-routing summaries in canonical result metadata |
| `src/controller/job_history_service.py` | Store richer workflow-video recent/history summaries |
| `src/gui/job_history_panel_v2.py` | Use generic video-artifact metadata for actions and display |
| `src/gui/views/video_workflow_tab_frame_v2.py` | Accept workflow-video handoff context cleanly |
| `src/gui/views/movie_clips_tab_frame_v2.py` | Accept workflow-video source bundles without special-case plumbing |
| `tests/pipeline/test_pipeline_runner.py` | Result-summary assertions |
| `tests/controller/test_job_history_service.py` | History convergence assertions |
| `tests/gui_v2/test_job_history_panel_v2.py` | Video action/handoff assertions |
| `tests/gui_v2/test_video_workflow_tab_frame_v2.py` | Workflow-tab handoff assertions |
| `tests/gui_v2/test_movie_clips_tab_v2.py` | Movie Clips handoff assertions |

### Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/controller/archive/` | No legacy runtime revival |
| `src/pipeline/job_requests_v2.py` | No submission-model changes |
| `src/controller/job_service.py` | No queue-policy changes in this PR |
| `docs/ARCHITECTURE_v2.6.md` | Architecture is already decided; only update roadmap/backlog if needed |

## Implementation Plan

### Step 1: Normalize generic workflow-video artifact bundles

Add a small helper layer that converts backend-local workflow-video output data
into one generic StableNew video bundle shape:

- primary output path
- output paths
- manifest paths
- preview path when available
- source image path
- frame directory or frame count when available
- handoff-safe bundle for history/UI

Files:

- create `src/video/video_artifact_helpers.py`
- modify `src/video/comfy_workflow_backend.py`

### Step 2: Preserve generic video routing in pipeline results

Teach `PipelineRunner` to always stamp workflow-video output into generic
result-summary fields, not only stage-specific keys.

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 3: Converge history/recent-output handling

Extend history services to consume the generic video bundle so recent-output and
history surfaces do not need stage-name heuristics for workflow-video.

Files:

- modify `src/controller/job_history_service.py`
- modify `tests/controller/test_job_history_service.py`

### Step 4: Unify GUI handoff surfaces

Use the generic video bundle in:

- Job History actions
- Video Workflow handoff
- Movie Clips source intake

Files:

- modify `src/gui/job_history_panel_v2.py`
- modify `src/gui/views/video_workflow_tab_frame_v2.py`
- modify `src/gui/views/movie_clips_tab_frame_v2.py`
- modify related GUI tests

### Step 5: Documentation and cleanup

If field names or canonical handoff behavior become part of the active product
story, update roadmap/backlog docs in the same PR.

## Testing Plan

### Unit Tests

- `tests/video/test_video_artifact_helpers.py`
- focused backend helper assertions in `tests/video/test_comfy_workflow_backend.py`

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`
- `tests/controller/test_job_history_service.py`
- `tests/gui_v2/test_job_history_panel_v2.py`
- `tests/gui_v2/test_video_workflow_tab_frame_v2.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`

### Manual Testing

1. Run one `video_workflow` job.
2. Confirm output lands under a deterministic run folder with manifest and
   canonical primary artifact.
3. Open History and verify the result can hand off cleanly to Video Workflow or
   Movie Clips as appropriate.

## Verification Criteria

### Success Criteria

1. Workflow-video jobs emit one generic video-artifact summary shape.
2. History and recent outputs no longer need workflow-stage special casing for
   basic routing and handoff.
3. Movie Clips can consume workflow-video outputs through a documented,
   deterministic handoff path.

### Failure Criteria

1. Stage-specific workflow-video handling remains the only source of truth.
2. History rows for workflow-video still lack a usable primary artifact.
3. GUI handoff requires backend-local or Comfy-local fields.

## Risk Assessment

### Low-Risk Areas

- Helper extraction for generic video bundles
- Test-only history and GUI assertions

### Medium-Risk Areas

- `PipelineRunner` result-summary changes
  - Mitigation: keep existing compatibility keys while adding stronger generic keys

### High-Risk Areas

- GUI handoff regressions across SVD, workflow-video, and Movie Clips
  - Mitigation: cover all three surfaces with focused GUI tests

### Rollback Plan

Revert the helper integration and restore prior stage-specific workflow-video
summary behavior while keeping the backend runtime intact.

## Tech Debt Analysis

### Tech Debt Removed

- thinner workflow-video history handling
- stage-name driven handoff assumptions for workflow-video

### Tech Debt Intentionally Deferred

- sequence-level routing and segment summaries
  - Owner: `PR-VIDEO-216`
- stitched/interpolated artifact routing
  - Owner: `PR-VIDEO-217`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal

- `src/video/comfy_workflow_backend.py`
- `src/pipeline/pipeline_runner.py`
- `src/controller/job_history_service.py`
- GUI history/video workflow/movie clips surfaces

### External

- Managed Comfy runtime only for manual workflow-video execution verification

## Approval & Execution

Planner: ChatGPT/Codex planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-VIDEO-215`.
2. Continue with `PR-VIDEO-216`.
3. Use the converged video bundle in later GUI polish work in `PR-GUI-220`.
