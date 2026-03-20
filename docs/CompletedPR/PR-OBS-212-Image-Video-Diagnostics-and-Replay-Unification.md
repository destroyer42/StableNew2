# PR-OBS-212 - Image/Video Diagnostics and Replay Unification

Status: Completed 2026-03-19

## Purpose

Unify the runtime observability contract so image and video runs produce the
same kind of replayable, backend-aware diagnostics summary.

This PR closes the gap between:

- pipeline result metadata
- diagnostics bundles
- job-service diagnostics snapshots
- replay-oriented result inspection

without introducing a second history or replay model.

## What Changed

### Canonical result contract

Added:

- `src/pipeline/result_contract_v26.py`

Delivered:

- canonical artifact collection across image and video results
- canonical primary-artifact extraction
- backend-aware replay descriptors that stay StableNew-owned
- diagnostics descriptors that summarize success, recovery classification,
  outputs, artifact type, primary stage, and backend/workflow identity

The new descriptors are intentionally backend-aware, but they do not leak raw
backend payloads or Comfy workflow JSON into higher-level contracts.

### Runner metadata now stamps canonical replay/diagnostics descriptors

Updated:

- `src/pipeline/pipeline_runner.py`

Delivered:

- every canonical `PipelineRunResult` now carries:
  - `metadata["replay_descriptor"]`
  - `metadata["diagnostics_descriptor"]`
- descriptors are emitted for both image and video runs
- image-only runs now use stage-plan fallback correctly instead of surfacing
  `"unknown"` as the primary stage when the raw executor result did not label it

### Job-service diagnostics now use the same runtime truth

Updated:

- `src/controller/job_service.py`

Delivered:

- `get_diagnostics_snapshot()` no longer emits a thin image-centric
  `result_summary`
- per-job diagnostics summaries now come from the same canonical result
  contract used by pipeline results
- video jobs surface backend/workflow identity in diagnostics without inventing
  a separate diagnostics schema just for video

### Diagnostics bundles now include replay/summary artifacts

Updated:

- `src/utils/diagnostics_bundle_v2.py`

Delivered:

- bundles still include the full `runtime/job_snapshot.json`
- when runtime job data is present, bundles also write:
  - `runtime/result_summary.json`
  - `runtime/replay_descriptor.json`
- queue-state inclusion was repaired while landing this PR, so
  `runtime/queue_state.json` remains part of the bundle contract when enabled

## Tests

Updated:

- `tests/pipeline/test_pipeline_runner.py`
- `tests/controller/test_job_service_unit.py`
- `tests/utils/test_diagnostics_bundle_v2.py`

Verified:

- `pytest tests/history/test_history_replay_integration.py tests/pipeline/test_replay_vs_fresh_v2.py tests/pipeline/test_pipeline_runner.py tests/controller/test_job_service_unit.py tests/utils/test_diagnostics_bundle_v2.py -q`
- `pytest --collect-only -q -rs` -> `2380 collected / 0 skipped`
- `python -m compileall src/pipeline/result_contract_v26.py src/pipeline/pipeline_runner.py src/controller/job_service.py src/utils/diagnostics_bundle_v2.py`

## Architectural Result

StableNew now has one replay/diagnostics truth across image and video:

- one outer job model: NJR
- one result-summary contract for diagnostics
- one replay-descriptor contract for backend-aware rerun context
- one crash-bundle story for image and video workloads

This keeps replay and diagnostics aligned with the v2.6 architecture instead of
letting video grow a parallel observability surface.

## Remaining Deferred Debt

Still owned by later PRs:

- residual GUI/history consumption cleanup for queue-only and video workflow UX:
  `PR-GUI-213`
- final compat-shim removal, remaining controller shrink, and last performance/
  stability polish: `PR-POLISH-214`

Next planned PR: `PR-GUI-213`
