# PR-CI-245 - CI Truth Sync and Smoke Suite Contract

Status: Specification
Priority: HIGH
Date: 2026-03-29

## Scope

- make CI run the named deterministic required smoke gate
- make machine-facing docs point to the same smoke gate
- keep issue templates and test-surface docs aligned with workflow truth

## Repo Truth

This scope is now delivered in code by:

- `.github/workflows/ci.yml`
- `tools/ci/run_required_smoke.py`
- `tests/system/test_ci_truth_sync_v2.py`
- `tests/TEST_SURFACE_MANIFEST.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`

## Validation

- `pytest tests/system/test_ci_truth_sync_v2.py -q`

