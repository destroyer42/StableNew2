# PR-CORE-011 - End-to-End Pipeline Tests

Status: Completed 2026-03-29

## Summary

StableNew already had a broad `golden_path` and `integration` test surface, so
the repo-truth gap for PR-CORE-011 was narrower than the original spec
claimed. This PR closed the missing native SVD and workflow-video golden-path
coverage by adding deterministic video integration tests that sit alongside the
existing AnimateDiff GP6 path.

## Delivered

- added `tests/integration/test_video_golden_paths_v26.py`
- validated native SVD through the active `AppController -> SVDController ->
  NJR -> PipelineRunner` path
- validated workflow-video runner execution with a deterministic dummy backend
  and canonical artifact metadata assertions
- confirmed the existing AnimateDiff GP6 golden-path test still passes beside
  the new video-path tests
- retired the stale PR-CORE-011 backlog spec and advanced the active queue to
  `PR-CORE-004`

## Key Files

- `tests/integration/test_video_golden_paths_v26.py`
- `tests/integration/test_golden_path_suite_v2_6.py`
- `docs/PR_Backlog/CORE_TOP_20_EXECUTABLE_MINI_ROADMAP_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

## Validation

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/integration/test_video_golden_paths_v26.py tests/integration/test_golden_path_suite_v2_6.py -k "gp6_animatediff_stage_creates_mp4_clip or gp6_svd_native_path_creates_video_artifact or gp6_video_workflow_path_creates_video_artifact" -q`
- result: `3 passed, 25 deselected in 0.41s`

## Notes

- `pytest.ini` already carried the needed `integration` and `golden_path`
  markers, so no discovery or CI configuration changes were required for this
  repo-truth closeout
- the next active CORE item is `PR-CORE-004 - Cinematic Prompt Template
  Library`