# PR-CI-253 - Mypy Smoke Gate and Whitelist Expansion

Status: Completed 2026-03-29

## Delivered

- CI now installs mypy and runs the named `tools/ci/run_mypy_smoke.py` gate
- the mypy smoke whitelist covers the shared kernel, controller ports, replay
  contract, and workflow-governance seams
- docs and issue-template surfaces now reference the named mypy smoke gate

## Validation

- `.venv\Scripts\python.exe tools/ci/run_mypy_smoke.py`
- `tests/system/test_ci_truth_sync_v2.py`
