# PR-CI-245 - CI Truth Sync and Smoke Suite Contract

Status: Completed 2026-03-29

## Delivered

- CI runs the named deterministic required smoke gate `tools/ci/run_required_smoke.py`
- machine-facing docs and issue templates now point at the same smoke contract
- a truth-sync test guards CI workflow drift

## Validation

- `tests/system/test_ci_truth_sync_v2.py`
- `.github/workflows/ci.yml`
- `tools/ci/run_required_smoke.py`

