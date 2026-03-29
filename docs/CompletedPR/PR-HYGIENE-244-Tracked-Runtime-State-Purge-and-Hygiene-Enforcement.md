# PR-HYGIENE-244 - Tracked Runtime State Purge and Hygiene Enforcement

Status: Completed 2026-03-29

## Delivered

- runtime-state paths are centralized behind `src/state/workspace_paths.py`
- mutable queue/UI/sidebar/preview/last-run state writes use the canonical workspace-path boundary
- tracked runtime state is kept out of git by policy and enforcement
- the short canonical hygiene contract now lives in `docs/TRACKED_RUNTIME_STATE_HYGIENE_v2.6.md`

## Validation

- `tests/safety/test_runtime_state_hygiene.py`

