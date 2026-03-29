# PR-UX-270 - Contextual Help Mode and Inspectable UI Language Polish

Status: Completed 2026-03-25

## Summary

This PR ties the recent UX-help work into a more coherent product layer by
adding a lightweight Help Mode and standardizing the shared guidance language on
the major queue-backed workspaces.

The result is a more consistent help experience across tab overviews, action
explainers, and the main window header.

## Delivered

- added `help_mode_enabled` state and toggle helpers to `AppStateV2`
- turned the existing header Help button into a real `Help Mode` toggle that
  updates product state instead of acting as a stub
- updated `TabOverviewPanel` so it now:
  - uses clearer `Show Guidance` / `Hide Guidance` wording
  - auto-expands when Help Mode is enabled
  - disables the local toggle while Help Mode is forcing expanded guidance
- updated `ActionExplainerPanel` to follow the same compact/expanded behavior so
  overview and action guidance behave consistently
- wired Help Mode through the main queue/help surfaces:
  - Pipeline overview
  - Review overview and workflow-action guidance
  - Learning overview and discovered/staged guidance panels
  - Queue action guidance
  - SVD, Video Workflow, and Movie Clips overviews and workflow explainers
- tightened shared wording in the central overview content to use `queue` more
  precisely where the action is queue-backed submission

## Key Files

- `src/gui/app_state_v2.py`
- `src/gui/main_window_v2.py`
- `src/controller/app_controller.py`
- `src/gui/widgets/action_explainer_panel_v2.py`
- `src/gui/widgets/tab_overview_panel_v2.py`
- `src/gui/panels_v2/queue_panel_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_action_explainer_panels_v2.py tests/gui_v2/test_tab_overview_panels_v2.py tests/gui_v2/test_main_window_smoke_v2.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_learning_tab_state_persistence.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_movie_clips_tab_v2.py tests/gui_v2/test_svd_tab_frame_v2.py -q`

Result:

- `96 passed, 2 skipped in 29.58s`

## Notes

- existing controller and Tk typing noise remains outside this PR scope
- the next canonical UX PR is `PR-UX-272-GUI-Audit-and-Consistency-Inventory`