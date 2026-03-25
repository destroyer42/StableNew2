# PR-UX-269 - Workflow Pathway Guidance and Use-Case Recommendations

Status: Completed 2026-03-25

## Summary

This PR adds a shared workflow-guidance layer so major image, learning, and
video surfaces explain when to use one pathway instead of another.

The product now gives explicit pathway guidance for:

- Review vs Learning
- discovered/imported review flows vs direct Review edits
- Staged Curation vs direct Review
- `Queue Now` vs `Edit in Review`
- SVD vs Video Workflow vs Movie Clips
- when secondary motion is better handled in workflow-driven video paths

## Delivered

- added shared GUI guidance helpers in
  `src/gui/help_text/workflow_guidance_v2.py`
- updated Review guidance copy so the default workspace hint and Review action
  panel explain when to stay in Review versus move into Learning
- added a new `Discovered Review` explainer to the Learning tab so operators can
  distinguish scan/import comparison flows from direct Review work
- updated staged-curation static help and live guidance strings so the bulk
  `Queue Now` path and single-candidate `Edit in Review` path are explicitly
  contrasted
- updated SVD, Video Workflow, and Movie Clips help panels to explain which
  video pathway is appropriate and when workflow-driven secondary motion is the
  better fit

## Key Files

- `src/gui/help_text/workflow_guidance_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/svd_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_action_explainer_panels_v2.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_learning_tab_state_persistence.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_movie_clips_tab_v2.py tests/gui_v2/test_svd_tab_frame_v2.py -q`

Result:

- `86 passed, 1 skipped in 5.63s`

## Notes

- existing Tk typing noise remains outside this PR scope
- the next canonical UX PR is `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`