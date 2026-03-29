# PR-HYGIENE-244 - Tracked Runtime State Purge and Hygiene Enforcement

Status: Specification
Priority: HIGH
Date: 2026-03-29

## Scope

- centralize mutable runtime state paths behind `src/state/workspace_paths.py`
- ensure queue/UI/sidebar/preview/last-run state writes use canonical workspace paths
- keep tracked runtime state out of git
- add a short canonical hygiene contract plus an enforcement test

## Repo Truth

This scope is now delivered in code by:

- `src/state/workspace_paths.py`
- `tests/safety/test_runtime_state_hygiene.py`
- runtime-state writers wired through `workspace_paths`

## Validation

- `pytest tests/safety/test_runtime_state_hygiene.py -q`

