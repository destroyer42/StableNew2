# PR-VIDEO-215 - Workflow-Video Output Routing and History Convergence

Status: Completed 2026-03-19

## Summary

This PR closed the gap between workflow-video execution and StableNew's
generic artifact/history model.

Workflow-video runs now emit one canonical video bundle shape that the runner,
history surfaces, Video Workflow, and Movie Clips can consume without relying
on backend-local or stage-name-specific assumptions.

## Delivered

- added `src/video/video_artifact_helpers.py` to normalize workflow-video
  outputs into one StableNew-owned bundle shape
- updated `src/video/comfy_workflow_backend.py` to emit richer artifact details
  for routing, manifests, previews, and handoff
- updated `src/pipeline/pipeline_runner.py` to preserve generic video routing
  summaries alongside compatibility keys
- converged `src/controller/job_history_service.py` and
  `src/gui/job_history_panel_v2.py` on generic video artifact metadata
- aligned `src/gui/views/video_workflow_tab_frame_v2.py` and
  `src/gui/views/movie_clips_tab_frame_v2.py` around handoff-safe video source
  bundles

## Key Files

- `src/video/video_artifact_helpers.py`
- `src/video/comfy_workflow_backend.py`
- `src/pipeline/pipeline_runner.py`
- `src/controller/job_history_service.py`
- `src/gui/job_history_panel_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`

## Tests

Focused regression coverage landed in:

- `tests/video/test_video_artifact_helpers.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/controller/test_job_history_service.py`
- `tests/gui_v2/test_job_history_panel_v2.py`
- `tests/gui_v2/test_video_workflow_tab_frame_v2.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Deferred Debt

Intentionally deferred:

- first-class long-form sequence orchestration
  Future owner: `PR-VIDEO-216`
- canonical stitched/interpolated assembly over sequence outputs
  Future owner: `PR-VIDEO-217`
- continuity metadata above individual jobs and sequences
  Future owner: `PR-VIDEO-218`