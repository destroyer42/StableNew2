# PR-CI-253 - Mypy Smoke Gate and Whitelist Expansion

Status: Completed 2026-03-29

## Purpose

Add a bounded type gate for the stabilized architecture seams without claiming
 the entire repo is fully typed.

## Delivered

- CI now runs `tools/ci/run_mypy_smoke.py`
- the smoke target list covers the shared app kernel, controller port layer,
  replay contract, and workflow-governance seams
- CI docs/templates now reference the named mypy smoke script instead of
  implying ad hoc type coverage

## Validation

- `tests/system/test_ci_truth_sync_v2.py`
- `.venv\Scripts\python.exe tools/ci/run_mypy_smoke.py`
