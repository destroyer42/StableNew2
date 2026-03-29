# Tracked Runtime State Hygiene v2.6

This document is the canonical short contract for mutable runtime state.

## Rules

- If the application writes a file during normal use, that file is runtime state and must not be tracked in git.
- Runtime state must live behind `src/state/workspace_paths.py`.
- Tests that need runtime state must redirect it to temp paths or deterministic fixtures.
- `tests/safety/test_runtime_state_hygiene.py` is the canonical enforcement check for tracked state drift.

## Canonical Mutable State Locations

- `state/`
- `data/learning/experiments/`
- `data/photo_optimize/assets/`

## Non-Goals

- This contract does not govern hand-authored fixtures under `tests/fixtures/`.
- This contract does not change runtime persistence behavior; it defines where that state may live and what must stay out of version control.
