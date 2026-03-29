# PR-HARDEN-281 - ADetailer Stability Closure and Request-Local Pinning Rollback

Status: Completed 2026-03-29

## Summary

This PR is now closed in substance. The active branch defaults ADetailer to the
global model/VAE switch path, keeps request-local pinning as an explicit opt-in
debug path, preserves the improved diagnostics, avoids restart recovery churn
for structured deterministic inference failures such as `NansException`, and
downgrades intentional request-local ambient model mismatch to contextual
logging instead of misleading drift warnings.

## Delivered

- `src/config/app_config.py` keeps
  `STABLENEW_ADETAILER_REQUEST_LOCAL_PINNING` default-off
- `src/pipeline/executor.py` keeps request-local ADetailer pinning fenced to
  the explicit opt-in path
- `src/pipeline/executor.py` treats structured `NansException` inference
  failures as stage failures rather than restart-triggering recovery incidents
- `src/pipeline/executor.py` logs intentional request-local ambient `/options`
  mismatch as contextual model-state information rather than a hard drift event
- focused test coverage now proves the default-global path, the opt-in
  request-local path, and the deterministic-failure no-restart behavior

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_generate_errors.py tests/api/test_webui_launch_profile_v2.py -q`

Result:

- `24 passed`

## Key Files

- `src/config/app_config.py`
- `src/pipeline/executor.py`
- `tests/pipeline/test_executor_adetailer.py`
- `tests/pipeline/test_executor_generate_errors.py`
- `tests/api/test_webui_launch_profile_v2.py`