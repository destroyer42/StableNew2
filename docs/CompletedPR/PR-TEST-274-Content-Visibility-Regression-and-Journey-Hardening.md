# PR-TEST-274 - Content Visibility Regression and Journey Hardening

Status: Completed 2026-03-27

## Summary

This PR closed the content-visibility feature series by adding deterministic
regression coverage for persistence, live GUI updates, learning-path metadata
normalization, and end-to-end restart behavior.

## Delivered

- added restart-persistence coverage in
  `tests/gui_v2/test_content_visibility_mode_persistence.py`
- added end-to-end toggle and restart journey coverage in
  `tests/journey/test_content_visibility_mode_journey.py`
- added learning-path normalization coverage in
  `tests/learning/test_content_visibility_learning_filters.py`
- hardened existing controller and GUI regressions so they no longer depend on
  whatever persisted UI-state file already exists on disk
- mapped stale spec-era GUI test names onto the repo's current suite instead of
  leaving the hardening plan partially applied

## Key Files

- `tests/gui_v2/test_content_visibility_mode_persistence.py`
- `tests/journey/test_content_visibility_mode_journey.py`
- `tests/learning/test_content_visibility_learning_filters.py`
- `tests/controller/test_job_history_service.py`
- `tests/gui_v2/test_main_window_persistence_regressions.py`
- `tests/gui_v2/test_job_history_panel_v2.py`
- `tests/gui_v2/test_queue_run_controls_restructure_v2.py`
- `tests/gui_v2/test_content_visibility_toggle_integration.py`

## Tests

Focused verification passed:

- `pytest -q tests/controller/test_job_history_service.py tests/learning/test_content_visibility_learning_filters.py`
- `pytest -q tests/gui_v2/test_content_visibility_mode_persistence.py tests/gui_v2/test_main_window_persistence_regressions.py tests/gui_v2/test_job_history_panel_v2.py tests/gui_v2/test_queue_run_controls_restructure_v2.py`
- `pytest -q tests/journey/test_content_visibility_mode_journey.py`
- `pytest tests/controller tests/learning -q -k "visibility"`
- `pytest tests/gui_v2 -q -k "visibility or sfw or nsfw"`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPlans/STAGED_CURATION_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/PR-TEST-274-Content-Visibility-Regression-and-Journey-Hardening.md`

## Notes

The original spec named a few outdated GUI test filenames. The implemented PR
applied the same coverage intent to the current repo test surface instead of
recreating stale file names.
