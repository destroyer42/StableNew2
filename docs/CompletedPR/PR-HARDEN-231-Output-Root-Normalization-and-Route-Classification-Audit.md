# PR-HARDEN-231 - Output Root Normalization and Route Classification Audit

Status: Completed 2026-03-20

## Summary

This PR hardened StableNew's output routing so configured `output_dir` values
are treated as base roots instead of accidentally carrying route-specific
suffixes. It also made existing-run classification trust manifest metadata
before falling back to folder-name heuristics.

## Delivered

- added canonical output-root normalization in `src/state/output_routing.py`
- stripped trailing known route folders before route selection
- made existing-output classification prefer manifest metadata over folder-name
  guesses
- added regressions proving a misconfigured `output/animatediff` root no longer
  traps normal Pipeline jobs

## Key Files

- `src/state/output_routing.py`
- `tests/state/test_output_routing.py`
- `tests/pipeline/test_output_folder_structure.py`

## Tests

Focused verification passed:

- `pytest tests/state/test_output_routing.py tests/pipeline/test_output_folder_structure.py -q`
- result: `12 passed`
- `python -m compileall src/state/output_routing.py tests/state/test_output_routing.py tests/pipeline/test_output_folder_structure.py`
- `pytest --collect-only -q -rs` -> `2580 collected / 0 skipped`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`

## Deferred Debt

Intentionally deferred:

- PromptPack selector cleanup and real refresh/discovery UX
  Future owner: `PR-GUI-232`
- canonical discovered scan-root cleanup in the learning tab
  Future owner: `PR-LEARN-233`
