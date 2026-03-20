# PR-TEST-211 - Test Taxonomy and Suite Normalization

Status: Completed 2026-03-19

## Purpose

Normalize the active test surface so canonical suites define current v2.6
runtime truth, compatibility coverage is explicit, and archive-era DTO imports
do not leak back into canonical subsystem tests.

## What Changed

### Canonical tests are archive-free

Updated:

- `tests/learning/test_learning_record_builder.py`
- `tests/pipeline/test_pipeline_adetailer_config.py`

Delivered:

- the learning-record builder test now uses a local canonical test config
  dataclass instead of importing archive `PipelineConfig`
- the ADetailer plan test now exercises canonical stage-plan construction
  directly instead of relying on the legacy controller-config helper path

### Legacy submission coverage moved to compat

Moved:

- `tests/integration/test_end_to_end_pipeline_v2.py`
  -> `tests/compat/test_end_to_end_legacy_submission_modes.py`

Delivered:

- archive-`PipelineConfig` and historical `DIRECT` submission semantics are now
  explicitly housed under `tests/compat/`
- canonical `tests/integration/` no longer carries archive DTO coverage

### Taxonomy enforcement and manifest cleanup

Added:

- `tests/system/test_test_taxonomy_enforcement_v26.py`

Updated:

- `tests/TEST_SURFACE_MANIFEST.md`

Delivered:

- a system-level enforcement test now fails if archive `PipelineConfig`
  imports appear outside compat-only test surfaces
- the manifest now distinguishes canonical, compat, and excluded buckets
- the CI gate language now explicitly prefers canonical runtime truth while
  keeping compat coverage separate and temporary

### Optional dependency baseline cleaned up

Updated:

- `tests/video/test_svd_postprocess_worker.py`

Delivered:

- the torchvision shim test is now deterministic regardless of whether
  `torchvision` is installed
- with both `opencv-python` and `torch` present, the previous optional-dependency
  skip is gone from the global collection baseline

## Verification

- `pytest tests/video/test_svd_postprocess_worker.py tests/learning/test_learning_record_builder.py tests/pipeline/test_pipeline_adetailer_config.py tests/system/test_test_taxonomy_enforcement_v26.py -q`
- `pytest tests/compat/test_end_to_end_legacy_submission_modes.py -k "history_entry_from_manual_run_config or history_entry_from_pack_run_config or pipeline_payload_includes_refiner_and_hires_config" -q`
- `rg -n "src\.controller\.archive|from\s+src\.controller\.archive|import\s+src\.controller\.archive" tests`
- `pytest --collect-only -q -rs` -> `2380 collected / 0 skipped`

## Architectural Result

StableNew now has a cleaner test contract:

- canonical subsystem tests no longer import archive runtime DTOs
- compatibility behavior is explicit under `tests/compat/`
- the collection baseline no longer relies on optional dependency skips
- future archive-import regressions in canonical tests are guarded by an
  enforcement test

## Remaining Deferred Debt

Still owned by later PRs:

- `submit_direct()` compatibility behavior and the remaining direct-path tests:
  `PR-POLISH-214`
- residual GUI `PipelineConfigPanel` naming and related shim history:
  `PR-GUI-213`
- image/video diagnostics and replay unification:
  `PR-OBS-212`

Next planned PR: `PR-OBS-212`
