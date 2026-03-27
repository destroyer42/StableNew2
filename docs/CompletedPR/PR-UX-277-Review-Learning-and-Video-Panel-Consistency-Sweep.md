# PR-UX-277 - Review, Learning, and Video Panel Consistency Sweep

Status: Completed 2026-03-26

## Summary

This PR extends the shared GUI dark-mode and resize discipline into the Review,
Learning, Staged Curation, and video workflow surfaces.

It replaces several remaining local pane-width rules with shared workspace
minimums, fixes overlapping row layouts in Review and Staged Curation, and
removes the last hard-coded prompt-editor text colors from the workflow-driven
video surfaces.

## Delivered

- added shared two-pane and three-pane workspace column helpers to the active
  layout contract
- moved the Review tab body and lower control region onto explicit shared
  workspace minimum widths
- fixed the Review tab row collision so the prompt/reprocess controls sit below
  the preview body instead of competing for the same grid row
- moved Learning designed, discovered, and staged notebook surfaces onto shared
  workspace minimum widths
- fixed the staged-curation action-band row overlap so decision, queue, and
  review actions stack predictably
- applied shared themed text/list styling to remaining high-value raw widgets on
  Review, Learning staged curation, Video Workflow, and Movie Clips
- added focused GUI regressions covering workspace minimums, staged row order,
  and themed text/list seams across the updated surfaces

## Key Files

- `src/gui/view_contracts/pipeline_layout_contract.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/svd_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`
- `tests/gui_v2/test_workspace_layout_resilience_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_pipeline_view_contracts.py tests/gui_v2/test_workspace_layout_resilience_v2.py tests/gui_v2/test_review_tab_prompt_modes.py tests/gui_v2/test_learning_tab_state_persistence.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_svd_tab_frame_v2.py tests/gui_v2/test_movie_clips_tab_v2.py -q`

Result:

- `79 passed, 1 skipped in 4.58s`

## Notes

- broader popup and inspector normalization still belongs to
  `PR-UX-278-Dialog-Inspector-and-Secondary-Surface-Consistency-Sweep`
- pre-existing Tk typing diagnostics remain in several older GUI modules and are
  outside this PR scope