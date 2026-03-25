# PR-UX-268 - Effective Config Summaries and Why This Value Is Used

Status: Completed 2026-03-25

## Summary

This PR expands read-only effective-settings visibility so operators can see not
just the active value, but why that value won.

It adds provenance-aware effective-settings summaries to:

- Review reprocess previews
- Learning staged-curation candidate previews
- Video Workflow settings
- Movie Clips settings

## Delivered

- extended `ReprocessEffectiveSettingsPreview` and `ReprocessStageSettingsPreview`
  with field-level source labels
- surfaced Review summaries that show:
  - source stage/model/vae
  - value-source precedence
  - inherited vs explicit prompt behavior
  - per-stage sampler/scheduler/steps/cfg/denoise provenance
- surfaced staged-curation `Effective Settings` previews for `Queue Now` target
  stages using the same typed preview model
- added lightweight effective-settings summaries on Video Workflow and Movie
  Clips that distinguish defaults from current explicit selections

## Key Files

- `src/pipeline/reprocess_builder.py`
- `src/gui/controllers/review_workflow_adapter.py`
- `src/controller/app_controller.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/pipeline/test_reprocess_builder_defaults.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_learning_tab_state_persistence.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_movie_clips_tab_v2.py -q`

Result:

- `75 passed, 1 skipped in 3.77s`

## Notes

- existing AppController type-check noise remains outside this PR scope
- the next canonical UX PR is `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`