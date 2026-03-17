# PR-ARCH-064: Architecture Enforcement Checks

## Summary

Add low-noise architecture guard tests so the repo automatically rejects a short
list of high-value violations:

- GUI modules must not import `pipeline_runner` or `executor` directly.
- GUI modules must not invoke runner entrypoints directly.
- Legacy `pipeline_config` archive imports must stay isolated to the current
  allowlisted legacy surfaces.
- `legacy_njr_adapter` must remain isolated to its own module.

This PR is intentionally test-only. It encodes Phase 1 architectural boundaries
without widening runtime behavior.

## Allowed Files

- `tests/system/test_architecture_enforcement_v2.py`
- `docs/PR_MAR26/PR-ARCH-064-Architecture-Enforcement-Checks.md`

## Implementation

1. Add file-scan invariant tests over `src/`.
2. Keep the archive import allowlist explicit:
   - `src/controller/app_controller.py`
   - `src/controller/pipeline_controller.py`
   - `src/pipeline/legacy_njr_adapter.py`
3. Ignore `archive/` directories so the checks enforce live code only.
4. Fail with concrete file/line diagnostics when a violation appears.

## Verification

- `pytest tests/system/test_architecture_enforcement_v2.py -q`
- `pytest tests/pipeline/test_txt2img_path_closeout_invariants.py tests/pipeline/test_job_ui_summary_v2.py -q`
- `pytest --collect-only -q`
- `python -m compileall tests/system/test_architecture_enforcement_v2.py tests/pipeline/test_job_ui_summary_v2.py src/pipeline/job_models_v2.py`

## Rollback

Revert the invariant test file and this PR record only. No runtime behavior is
introduced by the guard suite itself.
