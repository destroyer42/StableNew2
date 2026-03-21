# PR-LEARN-233 - Canonical Discovered Scan Root Fix

Status: Completed 2026-03-20

## Summary

This PR made the Learning tab rescan discovered experiments from the canonical
configured output root instead of guessing from transient GUI state.

## Delivered

- added canonical scan-root resolution in `LearningTabFrame`
- removed dependence on `app_state.output_dir` fallback behavior
- normalized route-suffixed output directories back to the base output root
- added focused regressions for routed output roots and rescan dispatch

## Key Files

- `src/gui/views/learning_tab_frame_v2.py`
- `tests/learning_v2/test_learning_output_root_resolution.py`

## Tests

Focused verification passed:

- `pytest tests/learning_v2/test_learning_output_root_resolution.py -q`
- `python -m compileall src/gui/views/learning_tab_frame_v2.py tests/learning_v2/test_learning_output_root_resolution.py`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/PR-LEARN-233-Canonical-Discovered-Scan-Root-Fix.md`

## Deferred Debt

Intentionally deferred:

- reprocess surface consolidation
  Future owner: `PR-GUI-234`
- Pipeline tab base-generation and recipe UX cleanup
  Future owner: `PR-GUI-235`
